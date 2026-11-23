"""HTTP API for VibePrompt / Invisible Grill."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request

from app.api.deps import (
    get_current_user,
    get_engine,
    get_knowledge_store,
    get_optional_user,
    get_repository,
    get_skill_registry,
    get_user_store,
    require_api_secret,
    require_authenticated_user,
    require_user,
    require_user_when_free_tier,
)
from app.auth.client_ip import hash_client_ip, resolve_client_ip
from app.auth.google_id_token import GoogleIdTokenError, verify_google_id_token
from app.auth.models import (
    AuthConfigPublic,
    AuthResponse,
    ChangePasswordRequest,
    GoogleAuthRequest,
    GuestAuthResponse,
    LoginRequest,
    ProfileSyncRequest,
    RegisterRequest,
    UserPublic,
    UserRecord,
)
from app.auth.security import (
    create_access_token,
    create_guest_token,
    hash_password,
    verify_password,
)
from app.byok.service import ByokValidationError, validate_and_save_byok
from app.compilation.agent_prompt import compile_agent_prompt
from app.compilation.prompt_pipeline import preview_skill_selection
from app.compilation.readiness import assess_readiness
from app.compilation.spec import compile_specification
from app.config import Settings, get_settings
from app.free_tier.models import ByokConfigPublic, ByokUpsertRequest, FreeTierStatus
from app.grill.context import apply_manual_context_update, project_context_view
from app.grill.decisions import update_decision_status
from app.grill.lifecycle import update_finding_status
from app.inference.router import build_status
from app.knowledge.store import KnowledgeStore
from app.orchestration.engine import FreeTierExhaustedError, GrillEngine
from app.persistence.repository import ProjectRepository
from app.persistence.user_store import UserStore
from app.projects.models import (
    AgentPromptRequest,
    AgentPromptResult,
    ChatRequest,
    ChatResponse,
    ContextUpdateRequest,
    Decision,
    DecisionUpdateRequest,
    Finding,
    FindingUpdateRequest,
    ProjectCreate,
    ProjectState,
    ProjectSummary,
    ReadinessResult,
    SpecificationResult,
)
from app.skills.registry import SkillRegistry

router = APIRouter(dependencies=[Depends(require_api_secret)])


def _http_free_tier_error(exc: FreeTierExhaustedError) -> HTTPException:
    status = 429 if exc.code == "rate_limited" else 402 if "exhausted" in exc.code or exc.code == "byok_required" else 403
    if exc.code == "auth_required":
        status = 401
    if exc.code == "platform_provider_unavailable":
        status = 503
    if exc.code == "duplicate_request":
        status = 409
    return HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": exc.message},
    )


def _assert_project_access(
    repo: ProjectRepository,
    project_id: str,
    user: UserRecord | None,
    settings: Settings,
    store: UserStore | None = None,
) -> ProjectState:
    from app.auth.authorization import assert_project_access

    return assert_project_access(repo, project_id, user, settings, store=store)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@router.get("/auth/config", response_model=AuthConfigPublic)
def auth_config(settings: Settings = Depends(get_settings)) -> AuthConfigPublic:
    """Public auth configuration for the frontend (no secrets)."""
    mode = settings.effective_auth_mode
    google_client_id = (settings.google_oauth_client_id or "").strip() or None
    return AuthConfigPublic(
        mode=mode,
        supabase_configured=settings.supabase_configured,
        google_oauth_hint=bool(google_client_id) or settings.supabase_google_oauth_enabled,
        github_oauth_hint=settings.supabase_github_oauth_enabled,
        google_client_id=google_client_id,
        email_auth=True,
        guest_sessions_enabled=True,
    )


@router.post("/auth/guest", response_model=GuestAuthResponse)
def mint_guest_session(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
) -> GuestAuthResponse:
    """
    Mint a short-lived guest JWT for SPA bootstrap.

    Replaces static VITE_API_SECRET. Enforces per-IP mint rate limits so Sybil
    loops cannot mint unlimited quota buckets. Forwarded-IP headers are ignored
    unless TRUSTED_PROXY_CIDRS matches the peer.
    """
    client_ip = resolve_client_ip(request, settings)
    ip_hash = hash_client_ip(client_ip)
    allowed, _ = store.check_and_increment_rate_limit(
        f"guest-mint:{ip_hash}",
        limit=settings.guest_mint_rate_limit_per_hour,
        window_seconds=3600,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "guest_mint_rate_limited",
                "message": "Too many guest sessions from this network. Sign in or configure BYOK.",
            },
        )

    user, session = store.create_guest_session(
        ip_hash=ip_hash,
        generations=settings.guest_free_tier_generations,
        expires_minutes=settings.guest_jwt_expires_minutes,
        provider=settings.free_tier_provider,
        model=settings.free_tier_model,
    )
    token = create_guest_token(
        guest_id=user.id,
        secret=settings.jwt_secret,
        expires_minutes=settings.guest_jwt_expires_minutes,
    )
    return GuestAuthResponse(
        access_token=token,
        expires_in_minutes=settings.guest_jwt_expires_minutes,
        generations_allocated=int(session["generations_allocated"]),
        user=store.to_public(user),
    )


@router.post("/auth/sync", response_model=UserPublic)
def sync_profile(
    body: ProfileSyncRequest | None = None,
    user: UserRecord = Depends(require_authenticated_user),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
) -> UserPublic:
    """Upsert application profile after Supabase Auth. User id comes from the JWT only."""
    hints = body or ProfileSyncRequest()
    provider = hints.auth_provider or user.auth_provider or "supabase"
    updated = store.upsert_supabase_user(
        user_id=user.id,
        email=user.email,
        display_name=hints.display_name or user.display_name,
        avatar_url=hints.avatar_url or user.avatar_url,
        auth_provider=provider,
    )
    if settings.free_tier_enabled:
        store.ensure_free_tier_allocation(
            updated.id,
            generations=settings.free_tier_generations,
            provider=settings.free_tier_provider,
            model=settings.free_tier_model,
        )
    return store.to_public(updated)


@router.post("/auth/register", response_model=AuthResponse)
def register(
    body: RegisterRequest,
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
) -> AuthResponse:
    if settings.effective_auth_mode == "supabase":
        raise HTTPException(
            status_code=400,
            detail=(
                "Email registration is handled by Supabase Auth. "
                "Use the signup page / Supabase client instead of this endpoint."
            ),
        )
    try:
        user = store.create_user(
            email=body.email,
            password_hash=hash_password(body.password),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if settings.free_tier_enabled:
        store.ensure_free_tier_allocation(
            user.id,
            generations=settings.free_tier_generations,
            provider=settings.free_tier_provider,
            model=settings.free_tier_model,
        )

    token = create_access_token(
        user_id=user.id,
        email=user.email,
        secret=settings.jwt_secret,
        expires_minutes=settings.jwt_expires_minutes,
    )
    return AuthResponse(access_token=token, user=store.to_public(user))


@router.post("/auth/login", response_model=AuthResponse)
def login(
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
) -> AuthResponse:
    if settings.effective_auth_mode == "supabase":
        raise HTTPException(
            status_code=400,
            detail=(
                "Email login is handled by Supabase Auth. "
                "Use the login page / Supabase client instead of this endpoint."
            ),
        )
    user = store.get_user_by_email(body.email)
    if (
        user is None
        or not user.password_hash
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Returning users must NOT receive another free-tier allocation.
    if settings.free_tier_enabled:
        store.ensure_free_tier_allocation(
            user.id,
            generations=settings.free_tier_generations,
            provider=settings.free_tier_provider,
            model=settings.free_tier_model,
        )

    token = create_access_token(
        user_id=user.id,
        email=user.email,
        secret=settings.jwt_secret,
        expires_minutes=settings.jwt_expires_minutes,
    )
    return AuthResponse(access_token=token, user=store.to_public(user))


@router.post("/auth/change-password")
def change_password(
    body: ChangePasswordRequest,
    user: UserRecord = Depends(require_user),
    store: UserStore = Depends(get_user_store),
) -> dict[str, str]:
    """Update the legacy password for the authenticated user."""
    if (
        not user.password_hash
        or not verify_password(body.current_password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    try:
        store.update_password_hash(user.id, hash_password(body.new_password))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/auth/google", response_model=AuthResponse)
def login_with_google(
    body: GoogleAuthRequest,
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
) -> AuthResponse:
    """Exchange a Google Identity Services ID token for a VibePrompt JWT."""
    client_id = (settings.google_oauth_client_id or "").strip()
    if not client_id:
        raise HTTPException(
            status_code=503,
            detail="Google Sign-In is not configured (set GOOGLE_OAUTH_CLIENT_ID)",
        )
    try:
        claims = verify_google_id_token(body.id_token, client_id=client_id)
    except GoogleIdTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    sub = str(claims["sub"])
    email = str(claims["email"]).strip().lower()
    display = str(claims.get("name") or "").strip() or None
    avatar = str(claims.get("picture") or "").strip() or None
    user_id = f"google_{sub}"

    try:
        user = store.upsert_supabase_user(
            user_id=user_id,
            email=email,
            display_name=display,
            avatar_url=avatar,
            auth_provider="google",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if settings.free_tier_enabled:
        store.ensure_free_tier_allocation(
            user.id,
            generations=settings.free_tier_generations,
            provider=settings.free_tier_provider,
            model=settings.free_tier_model,
        )

    token = create_access_token(
        user_id=user.id,
        email=user.email,
        secret=settings.jwt_secret,
        expires_minutes=settings.jwt_expires_minutes,
    )
    return AuthResponse(access_token=token, user=store.to_public(user))


@router.get("/auth/me", response_model=UserPublic)
def me(
    user: UserRecord = Depends(get_current_user),
    store: UserStore = Depends(get_user_store),
) -> UserPublic:
    return store.to_public(user)


# ---------------------------------------------------------------------------
# Free tier / BYOK
# ---------------------------------------------------------------------------


@router.get("/free-tier/status", response_model=FreeTierStatus)
def free_tier_status(
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord | None = Depends(get_optional_user),
) -> FreeTierStatus:
    return build_status(settings, store, user.id if user else None)


@router.get("/admin/free-tier-config")
def admin_free_tier_config(settings: Settings = Depends(get_settings)) -> dict:
    """Admin-safe config. Never returns the platform Qwen API key."""
    return settings.admin_free_tier_config()


@router.get("/byok", response_model=list[ByokConfigPublic])
def list_byok(
    user: UserRecord = Depends(require_user),
    store: UserStore = Depends(get_user_store),
) -> list[ByokConfigPublic]:
    return store.list_provider_configs(user.id)


@router.put("/byok", response_model=ByokConfigPublic)
async def upsert_byok(
    body: ByokUpsertRequest,
    user: UserRecord = Depends(require_user),
    store: UserStore = Depends(get_user_store),
    settings: Settings = Depends(get_settings),
) -> ByokConfigPublic:
    try:
        result = await validate_and_save_byok(
            store=store,
            settings=settings,
            user_id=user.id,
            request=body,
        )
    except ByokValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    org_id = store.ensure_user_org(user.id, user.email)
    store.emit_audit(
        org_id=org_id,
        user_id=user.id,
        action="byok.key_rotation",
        target_type="provider_config",
        target_id=body.provider,
        after={"provider": body.provider, "model": body.model},
    )
    return result


# ---------------------------------------------------------------------------
# Health / projects
# ---------------------------------------------------------------------------


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "status": "ok",
        "product": "VibePrompt Invisible Grill",
        "api_version": "v1",
        "providers": settings.provider_status(),
    }


@router.get("/health/ready")
def health_ready(
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
) -> dict:
    """Deep readiness: database connectivity + provider reachability hints."""
    from app.persistence.db import ping, redact_database_url

    backend, target = settings.resolved_database()
    db_ok = ping(backend, target)
    providers = settings.provider_status()
    primary_ok = bool(providers.get("primary_available"))
    ready = db_ok
    status = "ready" if ready else "not_ready"
    return {
        "status": status,
        "database": {
            "backend": backend,
            "ok": db_ok,
            "target": redact_database_url(target)
            if backend == "postgres"
            else target,
        },
        "providers": {
            "primary_available": primary_ok,
            "critic_available": providers.get("critic_available"),
            "order": providers.get("provider_order"),
        },
        "billing_configured": bool((settings.stripe_secret_key or "").strip()),
    }


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> list[ProjectSummary]:
    from app.auth.authorization import org_id_for_list, owner_id_for_list

    org_id = org_id_for_list(user, settings, store)
    if org_id:
        return repo.list_summaries(org_id=org_id)
    owner_id = owner_id_for_list(user, settings)
    return repo.list_summaries(owner_id=owner_id)


@router.post("/projects", response_model=ProjectState)
async def create_project(
    body: ProjectCreate,
    repo: ProjectRepository = Depends(get_repository),
    engine: GrillEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord | None = Depends(require_user_when_free_tier),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ProjectState:
    from app.auth.authorization import require_owner_for_create

    project = ProjectState(
        name=body.name.strip(),
        objective=(body.objective or "").strip(),
    )
    owner_id = require_owner_for_create(user, settings)
    org_id = None
    if user is not None:
        org_id = store.ensure_user_org(user.id, user.email)
    project = repo.create(project, owner_id=owner_id, org_id=org_id)
    if body.initial_message and body.initial_message.strip():
        try:
            await engine.handle_message(
                project.id,
                body.initial_message.strip(),
                user_id=owner_id,
                idempotency_key=idempotency_key,
            )
        except FreeTierExhaustedError as exc:
            raise _http_free_tier_error(exc) from exc
        refreshed = repo.get(project.id)
        if refreshed:
            return refreshed
    return project


@router.get("/projects/{project_id}", response_model=ProjectState)
def get_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> ProjectState:
    return _assert_project_access(repo, project_id, user, settings)


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> dict:
    _assert_project_access(repo, project_id, user, settings, store=store)
    org_id = repo.get_org_id(project_id) if hasattr(repo, "get_org_id") else None
    if not repo.delete(project_id, soft=True):
        raise HTTPException(status_code=404, detail="Project not found")
    if org_id:
        store.emit_audit(
            org_id=org_id,
            user_id=user.id if user else None,
            action="project.soft_delete",
            target_type="project",
            target_id=project_id,
        )
    return {"deleted": True, "soft": True}


@router.post("/projects/{project_id}/messages", response_model=ChatResponse)
async def send_message(
    project_id: str,
    body: ChatRequest,
    engine: GrillEngine = Depends(get_engine),
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ChatResponse:
    _assert_project_access(repo, project_id, user, settings)
    try:
        return await engine.handle_message(
            project_id,
            body.content,
            user_id=user.id if user else None,
            idempotency_key=idempotency_key,
            behavioural_mode=body.behavioural_mode,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    except FreeTierExhaustedError as exc:
        raise _http_free_tier_error(exc) from exc


@router.get("/projects/{project_id}/findings", response_model=list[Finding])
def list_findings(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> list[Finding]:
    project = _assert_project_access(repo, project_id, user, settings)
    return project.findings


@router.patch("/projects/{project_id}/findings/{finding_id}", response_model=Finding)
def update_finding(
    project_id: str,
    finding_id: str,
    body: FindingUpdateRequest,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> Finding:
    from app.auth.authorization import assert_can_resolve_finding

    project = assert_can_resolve_finding(repo, store, project_id, user, settings)
    finding = next((f for f in project.findings if f.id == finding_id), None)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    before = {"status": finding.status, "note": finding.resolution_note}
    try:
        update_finding_status(finding, body.status, body.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    repo.save(project)
    org_id = repo.get_org_id(project_id) if hasattr(repo, "get_org_id") else None
    if org_id:
        store.emit_audit(
            org_id=org_id,
            user_id=user.id if user else None,
            action="finding.status_change",
            target_type="finding",
            target_id=finding_id,
            before=before,
            after={"status": finding.status, "note": finding.resolution_note},
        )
        status_val = (
            finding.status.value
            if hasattr(finding.status, "value")
            else str(finding.status)
        )
        if status_val in ("resolved", "accepted_risk"):
            store.record_roi_event(
                org_id=org_id,
                event_type="finding_blocked_from_impl",
                project_id=project_id,
                user_id=user.id if user else None,
                payload={
                    "finding_id": finding_id,
                    "status": status_val,
                    "project_id": project_id,
                },
            )
        if (
            (finding.kind or "").lower() == "blocking_contradiction"
            and status_val == "open"
            and before.get("status") != "open"
        ):
            pass  # notifications on create handled in chat path
        # Promote project rejected approaches into org library
        for rej in project.rejected_approaches or []:
            store.upsert_org_rejected_approach(
                org_id=org_id,
                approach=rej.approach,
                reason=rej.reason,
                source_project_id=project_id,
                created_by=user.id if user else None,
            )
    return finding


@router.get("/projects/{project_id}/decisions", response_model=list[Decision])
def list_decisions(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> list[Decision]:
    project = _assert_project_access(repo, project_id, user, settings)
    return project.decisions


@router.patch("/projects/{project_id}/decisions/{decision_id}", response_model=Decision)
def update_decision(
    project_id: str,
    decision_id: str,
    body: DecisionUpdateRequest,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> Decision:
    """Accept, reject, or resolve a decision — preserves history; no silent overwrite of choice."""
    project = _assert_project_access(repo, project_id, user, settings)
    try:
        decision = update_decision_status(
            project,
            decision_id,
            status=body.status.value if hasattr(body.status, "value") else str(body.status),
            note=body.note,
            actor="user",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Decision not found") from None
    repo.save(project)
    return decision


@router.get("/projects/{project_id}/readiness", response_model=ReadinessResult)
def get_readiness(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> ReadinessResult:
    project = _assert_project_access(repo, project_id, user, settings, store=store)
    return assess_readiness(project)


@router.post("/projects/{project_id}/specification", response_model=SpecificationResult)
def generate_specification(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> SpecificationResult:
    from app.auth.authorization import assert_can_export_spec

    project = assert_can_export_spec(repo, store, project_id, user, settings)
    result = compile_specification(project)
    org_id = repo.get_org_id(project_id) if hasattr(repo, "get_org_id") else None
    if org_id:
        store.emit_audit(
            org_id=org_id,
            user_id=user.id if user else None,
            action="spec.export",
            target_type="project",
            target_id=project_id,
            after={"ready": result.readiness.ready if result.readiness else None},
        )
        ready = bool(
            result.readiness
            and (result.readiness.implementation_ready or result.readiness.ready)
        )
        store.record_roi_event(
            org_id=org_id,
            event_type="readiness_pass" if ready else "readiness_fail",
            project_id=project_id,
            user_id=user.id if user else None,
            payload={
                "project_id": project_id,
                "score_pct": result.readiness.score_pct if result.readiness else None,
                "ready": ready,
                "via": "spec_export",
            },
        )
    return result


@router.get("/projects/{project_id}/context")
def get_project_context(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> dict:
    """Inspect structured project context (Context Management Engine)."""
    project = _assert_project_access(repo, project_id, user, settings)
    return project_context_view(project)


@router.patch("/projects/{project_id}/context")
def update_project_context(
    project_id: str,
    body: ContextUpdateRequest,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> dict:
    """Correct or update stored project context without a chat turn."""
    project = _assert_project_access(repo, project_id, user, settings)
    updates = body.model_dump(exclude_unset=True)
    project, applied = apply_manual_context_update(project, updates)
    repo.save(project)
    return {"applied": applied, "context": project_context_view(project)}


@router.post("/projects/{project_id}/agent-prompt", response_model=AgentPromptResult)
def generate_agent_prompt(
    project_id: str,
    task: str | None = None,
    force: bool = False,
    agent: str = "cursor",
    include_skills: bool = True,
    body: AgentPromptRequest | None = Body(default=None),
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
    user_store: UserStore = Depends(get_user_store),
    store: KnowledgeStore = Depends(get_knowledge_store),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> AgentPromptResult:
    """
    Generate an agent-specific implementation prompt (Cursor / Antigravity / Codex).

    Blocked when not implementation-ready unless force=true.
    Query params remain supported; optional JSON body overrides them.
    """
    from app.auth.authorization import assert_can_export_spec

    project = assert_can_export_spec(repo, user_store, project_id, user, settings)
    req = body or AgentPromptRequest()
    result = compile_agent_prompt(
        project,
        task=req.task if req.task is not None else task,
        force=req.force or force,
        agent=req.agent or agent,
        include_skills=req.include_skills if body is not None else include_skills,
        user_selected_skills=req.user_selected_skills,
        refine_notes=req.refine_notes,
        registry=registry,
        store=store,
    )
    org_id = repo.get_org_id(project_id) if hasattr(repo, "get_org_id") else None
    if org_id:
        user_store.emit_audit(
            org_id=org_id,
            user_id=user.id if user else None,
            action="spec.agent_prompt_export",
            target_type="project",
            target_id=project_id,
            after={"agent": req.agent or agent, "force": req.force or force},
        )
    return result


@router.post("/projects/{project_id}/agent-prompt/preview-skills")
def preview_agent_prompt_skills(
    project_id: str,
    task: str | None = None,
    body: AgentPromptRequest | None = Body(default=None),
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
    store: KnowledgeStore = Depends(get_knowledge_store),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> dict:
    """Preview skill selection + readiness without compiling the full prompt."""
    project = _assert_project_access(repo, project_id, user, settings)
    req = body or AgentPromptRequest()
    return preview_skill_selection(
        project,
        task=req.task if req.task is not None else task,
        registry=registry,
        store=store,
        user_selected_skills=req.user_selected_skills or None,
    )


# ---------------------------------------------------------------------------
# Billing / audit / MFA / admin metrics
# ---------------------------------------------------------------------------


@router.post("/billing/checkout")
def billing_checkout(
    body: dict = Body(...),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
) -> dict:
    from app.billing.stripe_billing import create_checkout_session, stripe_enabled

    if not stripe_enabled(settings):
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    plan = str(body.get("plan") or "pro").lower()
    if plan not in ("pro", "team"):
        raise HTTPException(status_code=400, detail="plan must be pro or team")
    org_id = store.ensure_user_org(user.id, user.email)
    try:
        return create_checkout_session(
            settings,
            store,
            org_id=org_id,
            plan=plan,
            customer_email=user.email,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/billing/webhook")
async def billing_webhook(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict:
    from app.billing.stripe_billing import handle_webhook, stripe_enabled

    if not stripe_enabled(settings):
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    payload = await request.body()
    try:
        return handle_webhook(
            settings,
            store,
            payload=payload,
            signature=stripe_signature or "",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orgs/me")
def org_me(
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
) -> dict:
    org_id = store.ensure_user_org(user.id, user.email)
    role = store.get_membership_role(org_id, user.id)
    return {
        "org_id": org_id,
        "plan": store.get_org_plan(org_id),
        "role": role,
    }


@router.get("/orgs/{org_id}/audit")
def org_audit_log(
    org_id: str,
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
    limit: int = 100,
) -> dict:
    from app.persistence.tenancy import plan_includes_audit_log

    role = store.get_membership_role(org_id, user.id)
    if role is None and not settings.is_configured_admin(user.email):
        raise HTTPException(status_code=404, detail="Organization not found")
    plan = store.get_org_plan(org_id)
    if not plan_includes_audit_log(plan) and not settings.is_configured_admin(user.email):  # type: ignore[arg-type]
        raise HTTPException(
            status_code=403,
            detail="Audit log requires Team plan",
        )
    return {"org_id": org_id, "events": store.list_audit(org_id, limit=limit)}


@router.post("/auth/mfa/setup")
def mfa_setup(
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
) -> dict:
    from app.auth.mfa import generate_totp_secret, provisioning_uri

    secret = generate_totp_secret()
    store.set_mfa_secret(user.id, secret, enabled=False)
    return {
        "secret": secret,
        "otpauth_uri": provisioning_uri(secret, user.email or user.id),
    }


@router.post("/auth/mfa/enable")
def mfa_enable(
    body: dict = Body(...),
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
) -> dict:
    from app.auth.mfa import verify_totp

    row = store.get_mfa_secret(user.id)
    if not row:
        raise HTTPException(status_code=400, detail="Call /auth/mfa/setup first")
    secret, _ = row
    if not verify_totp(secret, str(body.get("code") or "")):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    store.set_mfa_secret(user.id, secret, enabled=True)
    org_id = store.ensure_user_org(user.id, user.email)
    store.emit_audit(
        org_id=org_id,
        user_id=user.id,
        action="auth.mfa_enabled",
        target_type="user",
        target_id=user.id,
    )
    return {"enabled": True}


@router.get("/admin/metrics")
def admin_metrics(
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
) -> dict:
    if not settings.is_configured_admin(user.email):
        raise HTTPException(status_code=403, detail="Admin only")
    return store.admin_usage_metrics()


# ---------------------------------------------------------------------------
# Phase 2: ROI, collaboration, playbooks
# ---------------------------------------------------------------------------


@router.get("/orgs/{org_id}/roi")
def org_roi(
    org_id: str,
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
) -> dict:
    role = store.get_membership_role(org_id, user.id)
    if role is None and not settings.is_configured_admin(user.email):
        raise HTTPException(status_code=404, detail="Organization not found")
    return store.org_roi_dashboard(org_id)


@router.post("/orgs/{org_id}/roi/agent-runs")
def report_roi_agent_runs(
    org_id: str,
    body: dict = Body(...),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
) -> dict:
    role = store.get_membership_role(org_id, user.id)
    if role is None and not settings.is_configured_admin(user.email):
        raise HTTPException(status_code=404, detail="Organization not found")
    project_id = str(body.get("project_id") or "")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")
    eid = store.report_agent_runs(
        org_id=org_id,
        project_id=project_id,
        user_id=user.id,
        runs_before=int(body.get("runs_before") or 0),
        runs_after=int(body.get("runs_after") or 0),
        notes=str(body.get("notes") or "") or None,
    )
    return {"id": eid, "dashboard": store.org_roi_dashboard(org_id)}


@router.get("/projects/{project_id}/findings/{finding_id}/comments")
def get_finding_comments(
    project_id: str,
    finding_id: str,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> dict:
    _assert_project_access(repo, project_id, user, settings, store=store)
    return {
        "comments": store.list_finding_comments(
            project_id=project_id, finding_id=finding_id
        )
    }


@router.post("/projects/{project_id}/findings/{finding_id}/comments")
def post_finding_comment(
    project_id: str,
    finding_id: str,
    body: dict = Body(...),
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
) -> dict:
    _assert_project_access(repo, project_id, user, settings, store=store)
    org_id = repo.get_org_id(project_id) if hasattr(repo, "get_org_id") else None
    if not org_id:
        org_id = store.ensure_user_org(user.id, user.email)
    text = str(body.get("body") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="body required")
    mentions = body.get("mentions") or []
    if not isinstance(mentions, list):
        mentions = []
    comment = store.add_finding_comment(
        org_id=org_id,
        project_id=project_id,
        finding_id=finding_id,
        user_id=user.id,
        body=text,
        mention_user_ids=[str(m) for m in mentions],
    )
    return comment


@router.get("/orgs/{org_id}/rejected-approaches")
def get_org_rejected(
    org_id: str,
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
) -> dict:
    role = store.get_membership_role(org_id, user.id)
    if role is None and not settings.is_configured_admin(user.email):
        raise HTTPException(status_code=404, detail="Organization not found")
    return {"items": store.list_org_rejected_approaches(org_id)}


@router.post("/orgs/{org_id}/rejected-approaches")
def post_org_rejected(
    org_id: str,
    body: dict = Body(...),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
) -> dict:
    role = store.get_membership_role(org_id, user.id)
    if role is None and not settings.is_configured_admin(user.email):
        raise HTTPException(status_code=404, detail="Organization not found")
    approach = str(body.get("approach") or "").strip()
    reason = str(body.get("reason") or "").strip()
    if not approach or not reason:
        raise HTTPException(status_code=400, detail="approach and reason required")
    return store.upsert_org_rejected_approach(
        org_id=org_id,
        approach=approach,
        reason=reason,
        source_project_id=str(body.get("source_project_id") or "") or None,
        created_by=user.id,
    )


@router.get("/notifications")
def get_notifications(
    store: UserStore = Depends(get_user_store),
    user: UserRecord = Depends(require_authenticated_user),
    limit: int = 50,
) -> dict:
    return {"items": store.list_notifications(user.id, limit=limit)}


@router.post("/orgs/{org_id}/playbooks")
def upload_org_playbook(
    org_id: str,
    body: dict = Body(...),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    registry: SkillRegistry = Depends(get_skill_registry),
    user: UserRecord = Depends(require_authenticated_user),
) -> dict:
    """Upload an internal playbook → draft Grill skill for the org."""
    from app.skills.verticals import playbook_to_skill

    role = store.get_membership_role(org_id, user.id)
    if role not in ("admin", "member") and not settings.is_configured_admin(user.email):
        raise HTTPException(status_code=403, detail="Members/admins only")
    title = str(body.get("title") or "").strip()
    content = str(body.get("content") or "").strip()
    vertical = str(body.get("vertical") or "").strip() or None
    if not title or not content:
        raise HTTPException(status_code=400, detail="title and content required")
    skill = playbook_to_skill(
        org_id=org_id, title=title, content=content, vertical=vertical
    )
    saved = registry.save(skill)
    pb = store.save_org_playbook(
        org_id=org_id,
        title=title,
        content_text=content,
        vertical=vertical,
        created_by=user.id,
        skill_id=saved.id,
    )
    store.emit_audit(
        org_id=org_id,
        user_id=user.id,
        action="playbook.uploaded",
        target_type="playbook",
        target_id=pb["id"],
        after={"skill_id": saved.id, "title": title},
    )
    return {"playbook": pb, "skill": {"id": saved.id, "slug": saved.slug, "status": saved.status.value}}


@router.get("/skills/verticals")
def list_vertical_packs(
    registry: SkillRegistry = Depends(get_skill_registry),
) -> dict:
    from app.skills.verticals import VERTICAL_SLUGS

    items = []
    for slug in VERTICAL_SLUGS:
        skill = registry.get_by_slug(slug)
        if skill:
            items.append(
                {
                    "id": skill.id,
                    "slug": skill.slug,
                    "name": skill.name,
                    "description": skill.description,
                    "status": skill.status.value,
                }
            )
    return {"items": items}


# ---------------------------------------------------------------------------
# Integrations: GitHub App + agent readiness gate
# ---------------------------------------------------------------------------


@router.get("/integrations/agent-gate/manifest")
def agent_gate_manifest() -> dict:
    from app.integrations.agent_gate import plugin_manifest

    return plugin_manifest()


@router.get("/integrations/agent-gate/{project_id}")
def agent_gate_status(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> dict:
    from app.integrations.agent_gate import build_gate_status

    project = _assert_project_access(repo, project_id, user, settings, store=store)
    return build_gate_status(project)


@router.post("/integrations/github/webhook")
async def github_webhook(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    repo: ProjectRepository = Depends(get_repository),
    engine: GrillEngine = Depends(get_engine),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
) -> dict:
    """
    GitHub App webhook: on pull_request opened/edited, create a Grill project
    from the PR body and return a check-style conclusion for the App to post.
    """
    from app.integrations.github_app import (
        extract_pr_review_brief,
        format_check_conclusion,
        parse_event,
        verify_github_signature,
    )
    from app.compilation.readiness import assess_readiness

    payload = await request.body()
    if not verify_github_signature(
        payload=payload,
        signature_header=x_hub_signature_256,
        secret=settings.github_webhook_secret,
    ):
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")

    if (x_github_event or "") not in {"pull_request", "ping"}:
        return {"ok": True, "ignored": True, "event": x_github_event}

    if x_github_event == "ping":
        return {"ok": True, "pong": True}

    try:
        event = parse_event(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    brief = extract_pr_review_brief(event)
    if brief is None:
        return {"ok": True, "ignored": True, "reason": "action_not_applicable"}

    owner_id = (settings.github_integration_user_id or "").strip() or None
    org_id = None
    if owner_id:
        try:
            org_id = store.ensure_user_org(owner_id, None)
        except Exception:
            org_id = None

    project = ProjectState(
        name=brief["name"],
        objective=brief["objective"],
    )
    project = repo.create(project, owner_id=owner_id, org_id=org_id)

    try:
        await engine.handle_message(
            project.id,
            brief["initial_message"],
            user_id=owner_id,
        )
    except FreeTierExhaustedError as exc:
        # Still return readiness of whatever state we have
        refreshed = repo.get(project.id) or project
        readiness = assess_readiness(refreshed).model_dump()
        check = format_check_conclusion(readiness)
        return {
            "ok": False,
            "error": exc.code,
            "project_id": project.id,
            "check": check,
            "meta": brief["meta"],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    refreshed = repo.get(project.id) or project
    readiness = assess_readiness(refreshed).model_dump()
    check = format_check_conclusion(readiness)

    # Notify org members of new blocking findings (in-app + optional email)
    if org_id:
        from app.integrations.email_notify import send_notification_email

        blockers = [
            f
            for f in refreshed.findings
            if f.status.value == "open"
            and (f.kind or "").lower() == "blocking_contradiction"
        ]
        members = store.list_org_member_ids(org_id)
        for f in blockers:
            store.notify_org_blocking_finding(
                org_id=org_id,
                project_id=refreshed.id,
                finding_id=f.id,
                title=f.title,
            )
        if blockers:
            emails = []
            for uid in members:
                u = store.get_user(uid)
                if (
                    u
                    and u.email
                    and "@" in u.email
                    and not u.email.endswith(".supabase")
                ):
                    emails.append(u.email)
            send_notification_email(
                settings,
                to_addresses=emails,
                subject=(
                    f"[VibePrompt] Blocking findings on "
                    f"{brief['meta'].get('repo')}#{brief['meta'].get('pr_number')}"
                ),
                body=(
                    f"Grill found {len(blockers)} blocking finding(s).\n"
                    f"Project: {refreshed.id}\n"
                    f"PR: {brief['meta'].get('html_url')}\n"
                    + "\n".join(f"- {f.title}" for f in blockers)
                ),
            )

    if org_id:
        store.emit_audit(
            org_id=org_id,
            user_id=owner_id,
            action="github.pr_review",
            target_type="project",
            target_id=project.id,
            after={"check": check, "meta": brief["meta"]},
        )

    return {
        "ok": True,
        "project_id": project.id,
        "check": check,
        "meta": brief["meta"],
        "agent_gate": f"/api/v1/integrations/agent-gate/{project.id}",
    }
