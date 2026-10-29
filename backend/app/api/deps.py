"""Shared FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Header, HTTPException, Request

from app.config import Settings, get_settings
from app.orchestration.engine import GrillEngine
from app.persistence.repository import ProjectRepository, SQLiteProjectRepository
from app.providers.factory import ProviderBundle, build_providers


@lru_cache
def get_repository() -> ProjectRepository:
    settings = get_settings()
    return SQLiteProjectRepository(settings.database_path)


@lru_cache
def get_provider_bundle() -> ProviderBundle:
    return build_providers(get_settings())


def get_engine() -> GrillEngine:
    settings = get_settings()
    bundle = get_provider_bundle()
    return GrillEngine(
        repo=get_repository(),
        primary=bundle.primary,
        critic=bundle.critic,
        settings=settings,
        using_offline_primary=bundle.using_offline_primary,
    )


def require_api_secret(
    request: Request,
    x_api_secret: str | None = Header(default=None),
) -> None:
    settings: Settings = get_settings()
    if not settings.api_secret:
        return
    if x_api_secret != settings.api_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing API secret")
