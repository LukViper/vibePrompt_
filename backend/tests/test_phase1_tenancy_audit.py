"""Phase 1: org tenancy, soft-delete, audit log, API v1 alias, ready health."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.persistence.repository import SQLiteProjectRepository
from app.persistence.user_store import UserStore
from app.projects.models import ProjectState


def _settings(db: Path) -> Settings:
    return Settings(
        app_env="development",
        database_path=str(db),
        database_backend="sqlite",
        jwt_secret="phase1-test-jwt-secret-at-least-32-chars",
        credentials_encryption_key="phase1-test-creds-secret-32chars!!",
        free_tier_enabled=False,
        demo_mode=True,
        api_secret="",
    )


def test_personal_org_audit_and_soft_delete():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "t.db"
        store = UserStore(str(db))
        repo = SQLiteProjectRepository(str(db))
        user = store.create_user(email="owner@example.com", password_hash="x")
        org_id = store.ensure_user_org(user.id, user.email)
        assert org_id
        assert store.get_membership_role(org_id, user.id) == "admin"
        assert store.get_org_plan(org_id) == "free"

        project = repo.create(
            ProjectState(name="Org Project", objective="tenancy"),
            owner_id=user.id,
            org_id=org_id,
        )
        assert repo.get_org_id(project.id) == org_id
        assert repo.get(project.id, org_id=org_id) is not None
        assert repo.get(project.id, org_id="org_other") is None

        store.emit_audit(
            org_id=org_id,
            user_id=user.id,
            action="finding.status_change",
            target_type="finding",
            target_id="f1",
            before={"status": "open"},
            after={"status": "resolved"},
        )
        events = store.list_audit(org_id)
        assert len(events) == 1
        assert events[0]["action"] == "finding.status_change"

        assert repo.delete(project.id, soft=True) is True
        assert repo.get(project.id) is None
        assert repo.list_summaries(org_id=org_id) == []


def test_api_v1_alias_and_ready_health(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "t.db"
        settings = _settings(db)

        def _gs():
            return settings

        monkeypatch.setattr("app.api.deps.get_settings", _gs)
        monkeypatch.setattr("app.config.get_settings", _gs)
        monkeypatch.setattr("app.main.get_settings", _gs)

        # Clear lru caches
        from app.api import deps

        deps.get_repository.cache_clear()
        deps.get_user_store.cache_clear()
        deps.get_knowledge_store.cache_clear()
        deps.get_skill_registry.cache_clear()
        deps.get_provider_bundle.cache_clear()

        app = create_app(settings)
        client = TestClient(app)
        r1 = client.get("/api/health")
        r2 = client.get("/api/v1/health")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.json().get("api_version") == "v1"

        ready = client.get("/api/v1/health/ready")
        assert ready.status_code == 200
        body = ready.json()
        assert body["database"]["backend"] == "sqlite"
        assert body["database"]["ok"] is True
