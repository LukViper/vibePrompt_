"""Centralized project authorization — independent of free-tier / subscription flags."""

from __future__ import annotations

from fastapi import HTTPException

from app.auth.models import UserRecord
from app.config import Settings
from app.persistence.repository import ProjectRepository
from app.projects.models import ProjectState


def assert_project_access(
    repo: ProjectRepository,
    project_id: str,
    user: UserRecord | None,
    settings: Settings,
) -> ProjectState:
    """
    Load a project and enforce ownership.

    Rules:
    - Missing project → 404.
    - Explicitly configured admins (ADMIN_EMAILS) may access any project.
    - Production (or auth-required modes): caller must be authenticated; owner must match.
    - Development: anonymous access allowed only for unowned projects; if a user is
      present and the project has an owner, ownership is always enforced — including
      when FREE_TIER_ENABLED is false.
    """
    project = repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    owner = repo.get_owner(project_id)

    if user is not None and settings.is_configured_admin(user.email):
        return project

    auth_required = settings.requires_authentication
    if auth_required and user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    if user is not None:
        if owner is None:
            # Authenticated caller on an unowned legacy/local project: allow in
            # development only; deny in production (orphans must not leak).
            if auth_required:
                raise HTTPException(status_code=404, detail="Project not found")
            return project
        if owner != user.id:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    # Anonymous (development only — auth_required already gated above)
    if owner is not None:
        # Owned projects are never readable anonymously
        raise HTTPException(status_code=401, detail="Authentication required")
    return project


def owner_id_for_list(
    user: UserRecord | None,
    settings: Settings,
) -> str | None:
    """
    Scope project listings.

    Authenticated users always see only their own projects (admins with
    ADMIN_EMAILS configured see all when listing with owner_id=None).
    """
    if user is not None and settings.is_configured_admin(user.email):
        return None
    if user is not None:
        return user.id
    if settings.requires_authentication:
        raise HTTPException(status_code=401, detail="Authentication required")
    return None


def require_owner_for_create(
    user: UserRecord | None,
    settings: Settings,
) -> str | None:
    """Return owner_id to stamp on create; require auth in secured modes."""
    if settings.requires_authentication and user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user.id if user else None
