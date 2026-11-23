"""Centralized project authorization — ownership + org RBAC."""

from __future__ import annotations

from fastapi import HTTPException

from app.auth.models import UserRecord
from app.config import Settings
from app.persistence.repository import ProjectRepository
from app.persistence.tenancy import (
    role_can_export_specs,
    role_can_resolve_findings,
)
from app.persistence.user_store import UserStore
from app.projects.models import ProjectState


def assert_project_access(
    repo: ProjectRepository,
    project_id: str,
    user: UserRecord | None,
    settings: Settings,
    *,
    store: UserStore | None = None,
    org_id: str | None = None,
) -> ProjectState:
    """
    Load a project and enforce ownership / org membership.

    Rules:
    - Missing / soft-deleted project → 404.
    - Explicitly configured admins (ADMIN_EMAILS) may access any project.
    - When org_id is set on the project, membership in that org is required.
    - Otherwise fall back to owner_id match (legacy personal projects).
    """
    project = repo.get(project_id, org_id=org_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    owner = repo.get_owner(project_id)
    project_org = None
    if hasattr(repo, "get_org_id"):
        project_org = repo.get_org_id(project_id)

    if user is not None and settings.is_configured_admin(user.email):
        return project

    auth_required = settings.requires_authentication
    if auth_required and user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    if user is not None and project_org and store is not None:
        role = store.get_membership_role(project_org, user.id)
        if role is None and owner != user.id:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    if user is not None:
        if owner is None:
            if auth_required:
                raise HTTPException(status_code=404, detail="Project not found")
            return project
        if owner != user.id:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    if owner is not None or project_org is not None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return project


def assert_can_resolve_finding(
    repo: ProjectRepository,
    store: UserStore,
    project_id: str,
    user: UserRecord | None,
    settings: Settings,
) -> ProjectState:
    project = assert_project_access(repo, project_id, user, settings, store=store)
    if user is None:
        if settings.requires_authentication:
            raise HTTPException(status_code=401, detail="Authentication required")
        return project
    org_id = repo.get_org_id(project_id) if hasattr(repo, "get_org_id") else None
    if not org_id:
        return project
    role = store.get_membership_role(org_id, user.id)
    if role is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    if not role_can_resolve_findings(role):  # type: ignore[arg-type]
        raise HTTPException(
            status_code=403,
            detail="Viewers cannot resolve findings",
        )
    return project


def assert_can_export_spec(
    repo: ProjectRepository,
    store: UserStore,
    project_id: str,
    user: UserRecord | None,
    settings: Settings,
) -> ProjectState:
    project = assert_project_access(repo, project_id, user, settings, store=store)
    if user is None:
        if settings.requires_authentication:
            raise HTTPException(status_code=401, detail="Authentication required")
        return project
    org_id = repo.get_org_id(project_id) if hasattr(repo, "get_org_id") else None
    if not org_id:
        return project
    role = store.get_membership_role(org_id, user.id)
    if role is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    if not role_can_export_specs(role):  # type: ignore[arg-type]
        raise HTTPException(
            status_code=403,
            detail="Viewers cannot export specifications",
        )
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


def org_id_for_list(
    user: UserRecord | None,
    settings: Settings,
    store: UserStore | None,
) -> str | None:
    """Prefer org-scoped listing when the user has a default org."""
    if user is not None and settings.is_configured_admin(user.email):
        return None
    if user is not None and store is not None:
        org_id = store.get_default_org_id(user.id) or store.ensure_user_org(
            user.id, user.email
        )
        return org_id
    return None


def require_owner_for_create(
    user: UserRecord | None,
    settings: Settings,
) -> str | None:
    """Return owner_id to stamp on create; require auth in secured modes."""
    if settings.requires_authentication and user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user.id if user else None
