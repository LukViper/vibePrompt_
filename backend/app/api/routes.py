"""HTTP API for VibePrompt / Invisible Grill."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException

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
from app.auth.models import (
    AuthConfigPublic,
    AuthResponse,
    LoginRequest,
    ProfileSyncRequest,
    RegisterRequest,
    UserPublic,
    UserRecord,
)
from app.auth.security import create_access_token, hash_password, verify_password
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
) -> ProjectState:
    from app.auth.authorization import assert_project_access

    return assert_project_access(repo, project_id, user, settings)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@router.get("/auth/config", response_model=AuthConfigPublic)
def auth_config(settings: Settings = Depends(get_settings)) -> AuthConfigPublic:
    """Public auth configuration for the frontend (no secrets)."""
    mode = settings.effective_auth_mode
    return AuthConfigPublic(
        mode=mode,
        supabase_configured=settings.supabase_configured,
        google_oauth_hint=settings.supabase_google_oauth_enabled,
        github_oauth_hint=settings.supabase_github_oauth_enabled,
        email_auth=True,
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
        return await validate_and_save_byok(
            store=store,
            settings=settings,
            user_id=user.id,
            request=body,
        )
    except ByokValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Health / projects
# ---------------------------------------------------------------------------


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "status": "ok",
        "product": "VibePrompt Invisible Grill",
        "providers": settings.provider_status(),
    }


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects(
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> list[ProjectSummary]:
    from app.auth.authorization import owner_id_for_list

    owner_id = owner_id_for_list(user, settings)
    return repo.list_summaries(owner_id=owner_id)


@router.post("/projects", response_model=ProjectState)
async def create_project(
    body: ProjectCreate,
    repo: ProjectRepository = Depends(get_repository),
    engine: GrillEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ProjectState:
    from app.auth.authorization import require_owner_for_create

    project = ProjectState(
        name=body.name.strip(),
        objective=(body.objective or "").strip(),
    )
    owner_id = require_owner_for_create(user, settings)
    project = repo.create(project, owner_id=owner_id)
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
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> dict:
    _assert_project_access(repo, project_id, user, settings)
    if not repo.delete(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": True}


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
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> Finding:
    project = _assert_project_access(repo, project_id, user, settings)
    finding = next((f for f in project.findings if f.id == finding_id), None)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    update_finding_status(finding, body.status, body.note)
    repo.save(project)
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
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> ReadinessResult:
    project = _assert_project_access(repo, project_id, user, settings)
    return assess_readiness(project)


@router.post("/projects/{project_id}/specification", response_model=SpecificationResult)
def generate_specification(
    project_id: str,
    repo: ProjectRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    user: UserRecord | None = Depends(require_user_when_free_tier),
) -> SpecificationResult:
    project = _assert_project_access(repo, project_id, user, settings)
    return compile_specification(project)


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
    store: KnowledgeStore = Depends(get_knowledge_store),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> AgentPromptResult:
    """
    Generate an agent-specific implementation prompt (Cursor / Antigravity / Codex).

    Blocked when not implementation-ready unless force=true.
    Query params remain supported; optional JSON body overrides them.
    """
    project = _assert_project_access(repo, project_id, user, settings)
    req = body or AgentPromptRequest()
    return compile_agent_prompt(
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
