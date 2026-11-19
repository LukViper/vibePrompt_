"""Shared FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import Depends, Header, HTTPException, Request

from app.auth.models import UserRecord
from app.auth.security import decode_access_token
from app.auth.supabase_jwt import SupabaseAuthError, verify_supabase_access_token
from app.config import Settings, get_settings
from app.knowledge.store import KnowledgeStore
from app.orchestration.engine import GrillEngine
from app.persistence.repository import ProjectRepository, SQLiteProjectRepository
from app.persistence.user_store import UserStore
from app.providers.factory import ProviderBundle, build_providers
from app.skills.registry import SkillRegistry


@lru_cache
def get_repository() -> ProjectRepository:
    settings = get_settings()
    return SQLiteProjectRepository(settings.database_path)


@lru_cache
def get_user_store() -> UserStore:
    settings = get_settings()
    return UserStore(settings.database_path)


@lru_cache
def get_knowledge_store() -> KnowledgeStore:
    settings = get_settings()
    return KnowledgeStore(
        settings.database_path,
        skills_root=settings.skills_dir,
        upload_root=settings.knowledge_upload_dir,
    )


@lru_cache
def get_skill_registry() -> SkillRegistry:
    return SkillRegistry(get_knowledge_store())


@lru_cache
def get_provider_bundle() -> ProviderBundle:
    return build_providers(get_settings())


def get_engine(
    settings: Settings = Depends(get_settings),
    repo: ProjectRepository = Depends(get_repository),
    store: UserStore = Depends(get_user_store),
) -> GrillEngine:
    # When free tier is enabled, per-request routing replaces this bundle for AI calls.
    bundle = build_providers(settings)
    return GrillEngine(
        repo=repo,
        primary=bundle.primary,
        critic=bundle.critic,
        settings=settings,
        using_offline_primary=bundle.using_offline_primary,
        user_store=store,
    )


_PUBLIC_API_SUFFIXES = (
    "/health",
    "/health/ready",
    "/auth/config",
    "/auth/guest",
    "/auth/register",
    "/auth/login",
    "/auth/google",
    "/billing/webhook",
)


def _is_public_bootstrap_path(path: str) -> bool:
    normalized = (path or "").rstrip("/") or "/"
    return any(normalized.endswith(suffix) for suffix in _PUBLIC_API_SUFFIXES)


def _bearer_payload_ok(token: str, settings: Settings) -> bool:
    try:
        payload = decode_access_token(token, settings.jwt_secret)
    except jwt.PyJWTError:
        return False
    return bool(payload.get("sub"))


def require_api_secret(
    request: Request,
    x_api_secret: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Shared API gate for browser + ops clients.

    Prefer short-lived Bearer JWTs (user or guest). Static X-API-Secret remains
    valid for server-to-server/ops curl — it must NOT be bundled in the SPA.
    Bootstrap auth routes are public so the SPA can mint a guest JWT first.
    """
    if _is_public_bootstrap_path(request.url.path):
        return

    token = _bearer_token(authorization)
    if token and _bearer_payload_ok(token, settings):
        return

    secret = (settings.api_secret or "").strip()
    if settings.is_production:
        if not secret:
            raise HTTPException(
                status_code=503,
                detail="Server misconfigured: API_SECRET required in production",
            )
        if x_api_secret and x_api_secret == secret:
            return
        raise HTTPException(
            status_code=401,
            detail="Authentication required (Bearer guest/user JWT or X-API-Secret)",
        )
    if not secret:
        return
    if x_api_secret == secret:
        return
    raise HTTPException(
        status_code=401,
        detail="Authentication required (Bearer guest/user JWT or X-API-Secret)",
    )


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


def _user_from_supabase_token(
    token: str,
    settings: Settings,
    store: UserStore,
) -> UserRecord | None:
    try:
        verified = verify_supabase_access_token(
            token,
            supabase_url=settings.supabase_url,
            jwt_issuer=settings.supabase_issuer or None,
            jwks_url=settings.supabase_jwks or None,
            jwt_secret=settings.supabase_jwt_secret or None,
        )
    except SupabaseAuthError:
        return None
    # Ensure a local profile exists so BYOK / free-tier / ownership keep working.
    return store.upsert_supabase_user(
        user_id=verified.id,
        email=verified.email,
        auth_provider="supabase",
    )


def _user_from_legacy_token(
    token: str,
    settings: Settings,
    store: UserStore,
) -> UserRecord | None:
    try:
        payload = decode_access_token(token, settings.jwt_secret)
    except jwt.PyJWTError:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = store.get_user(str(user_id))
    if user is None:
        return None
    if (payload.get("role") or user.auth_provider) == "guest":
        if store.guest_session_expired(str(user_id)):
            return None
    return user


def get_optional_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
) -> UserRecord | None:
    token = _bearer_token(authorization)
    if not token:
        return None
    mode = settings.effective_auth_mode
    if mode == "supabase":
        user = _user_from_supabase_token(token, settings, store)
        if user:
            return user
        # Fall through only if legacy also allowed? No — reject soft for optional.
        return None
    # legacy / auto without supabase
    if settings.supabase_configured:
        user = _user_from_supabase_token(token, settings, store)
        if user:
            return user
    return _user_from_legacy_token(token, settings, store)


def get_current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
) -> UserRecord:
    """Alias for require_authenticated_user — identity always from verified token."""
    return require_authenticated_user(
        authorization=authorization, settings=settings, store=store
    )


def require_authenticated_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
) -> UserRecord:
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    mode = settings.effective_auth_mode
    if mode == "supabase":
        try:
            verified = verify_supabase_access_token(
                token,
                supabase_url=settings.supabase_url,
                jwt_issuer=settings.supabase_issuer or None,
                jwks_url=settings.supabase_jwks or None,
                jwt_secret=settings.supabase_jwt_secret or None,
            )
        except SupabaseAuthError as exc:
            raise HTTPException(
                status_code=401,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        return store.upsert_supabase_user(
            user_id=verified.id,
            email=verified.email,
            auth_provider="supabase",
        )

    if settings.supabase_configured:
        user = _user_from_supabase_token(token, settings, store)
        if user:
            return user

    user = _user_from_legacy_token(token, settings, store)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


# Backward-compatible names used throughout the codebase
require_user = require_authenticated_user


def require_user_when_free_tier(
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None),
    store: UserStore = Depends(get_user_store),
) -> UserRecord | None:
    """
    Resolve the caller for project routes.

    Authentication is required in production and when free-tier auth is enabled.
    Ownership is enforced separately in assert_project_access for every env.
    """
    user = get_optional_user(authorization=authorization, settings=settings, store=store)
    if settings.requires_authentication and user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


# Alias reflecting broader use beyond free tier
require_project_user = require_user_when_free_tier


def require_admin(
    user: UserRecord = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> UserRecord:
    if settings.free_tier_enabled and not settings.admin_email_list:
        raise HTTPException(
            status_code=403,
            detail="ADMIN_EMAILS must be configured when free tier is enabled",
        )
    if not settings.is_admin_email(user.email):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user
