"""Security regression: ownership, production secrets, API_SECRET enforcement."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.persistence.repository import InMemoryProjectRepository, SQLiteProjectRepository
from app.persistence.user_store import UserStore
from app.providers.mock import MockProvider, heuristic_primary


def _settings(**kwargs) -> Settings:
    get_settings.cache_clear()
    base = dict(
        gemini_api_key="",
        openrouter_api_key="",
        groq_api_key="",
        qwen_api_key="",
        free_tier_enabled=False,
        critic_enabled=False,
        review_intensity="normal",
        database_path="./data/test_security.db",
        api_secret="",
        app_env="development",
        jwt_secret="test-jwt-secret-key-32bytes-min!!",
        credentials_encryption_key="test-creds-encryption-key-32b!!",
    )
    base.update(kwargs)
    return Settings(**base)


def _build_client(
    settings: Settings,
    *,
    repo: InMemoryProjectRepository | None = None,
    db_path: str | None = None,
) -> tuple[TestClient, InMemoryProjectRepository | SQLiteProjectRepository, UserStore | None]:
    get_settings.cache_clear()
    from app.api import deps
    from app.main import create_app
    from app.orchestration.engine import GrillEngine

    if repo is None:
        repo = InMemoryProjectRepository()
    store: UserStore | None = None
    if db_path:
        store = UserStore(db_path)
        settings.database_path = db_path

    primary = MockProvider(primary_handler=heuristic_primary)

    def _engine() -> GrillEngine:
        return GrillEngine(
            repo=repo,
            primary=primary,
            critic=None,
            settings=settings,
            using_offline_primary=True,
            user_store=store,
        )

    app = create_app()
    app.dependency_overrides[deps.get_repository] = lambda: repo
    app.dependency_overrides[deps.get_settings] = lambda: settings
    app.dependency_overrides[deps.get_engine] = _engine
    if store is not None:
        app.dependency_overrides[deps.get_user_store] = lambda: store
    from app.config import get_settings as cfg_get

    app.dependency_overrides[cfg_get] = lambda: settings

    client = TestClient(app)
    return client, repo, store


def _register(client: TestClient, email: str, password: str = "password123") -> dict:
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _auth_headers(token: str, api_secret: str = "") -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if api_secret:
        headers["X-API-Secret"] = api_secret
    return headers


@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    return str(tmp_path / "sec.db")


@pytest.mark.parametrize("free_tier", [False, True])
def test_user_a_cannot_access_user_b_project(tmp_db: str, free_tier: bool):
    settings = _settings(
        free_tier_enabled=free_tier,
        qwen_api_key="platform-key" if free_tier else "",
        auth_required_when_free_tier=True,
    )
    # SQLite repo so owner_id persists like production
    repo = SQLiteProjectRepository(tmp_db)
    client, _, _ = _build_client(settings, repo=repo, db_path=tmp_db)

    a = _register(client, "a@example.com")
    b = _register(client, "b@example.com")
    ha = _auth_headers(a["access_token"])
    hb = _auth_headers(b["access_token"])

    created = client.post(
        "/api/projects",
        headers=ha,
        json={"name": "A-Project", "objective": "Owned by A"},
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    # B cannot get / delete / message / readiness / agent-prompt
    for method, path in (
        ("get", f"/api/projects/{project_id}"),
        ("delete", f"/api/projects/{project_id}"),
        ("get", f"/api/projects/{project_id}/context"),
        ("get", f"/api/projects/{project_id}/readiness"),
        ("post", f"/api/projects/{project_id}/specification"),
        ("post", f"/api/projects/{project_id}/agent-prompt"),
        ("post", f"/api/projects/{project_id}/agent-prompt/preview-skills"),
    ):
        if method == "get":
            res = client.get(path, headers=hb)
        elif method == "delete":
            res = client.delete(path, headers=hb)
        else:
            res = client.post(path, headers=hb, json={})
        assert res.status_code == 404, f"{method} {path} -> {res.status_code} {res.text}"

    msg = client.post(
        f"/api/projects/{project_id}/messages",
        headers=hb,
        json={"content": "hijack attempt"},
    )
    assert msg.status_code == 404

    # A still can
    ok = client.get(f"/api/projects/{project_id}", headers=ha)
    assert ok.status_code == 200
    assert ok.json()["name"] == "A-Project"

    # B list does not include A's project
    listed = client.get("/api/projects", headers=hb)
    assert listed.status_code == 200
    assert all(p["id"] != project_id for p in listed.json())


def test_conversation_and_context_isolated(tmp_db: str):
    settings = _settings()
    repo = SQLiteProjectRepository(tmp_db)
    client, _, _ = _build_client(settings, repo=repo, db_path=tmp_db)

    a = _register(client, "owner@example.com")
    b = _register(client, "intruder@example.com")
    ha = _auth_headers(a["access_token"])
    hb = _auth_headers(b["access_token"])

    pa = client.post(
        "/api/projects",
        headers=ha,
        json={"name": "Secret", "objective": "private", "initial_message": "classified plan"},
    )
    assert pa.status_code == 200
    aid = pa.json()["id"]

    pb = client.post(
        "/api/projects",
        headers=hb,
        json={"name": "Other", "objective": "other"},
    )
    bid = pb.json()["id"]

    stolen = client.get(f"/api/projects/{aid}", headers=hb)
    assert stolen.status_code == 404

    ctx = client.get(f"/api/projects/{aid}/context", headers=hb)
    assert ctx.status_code == 404

    own = client.get(f"/api/projects/{bid}", headers=hb)
    assert own.status_code == 200
    assert all(
        "classified" not in (m.get("content") or "").lower()
        for m in own.json().get("messages", [])
    )


def test_agent_prompt_export_is_ownership_protected(tmp_db: str):
    settings = _settings()
    repo = SQLiteProjectRepository(tmp_db)
    client, _, _ = _build_client(settings, repo=repo, db_path=tmp_db)
    a = _register(client, "prompt-a@example.com")
    b = _register(client, "prompt-b@example.com")
    ha = _auth_headers(a["access_token"])
    hb = _auth_headers(b["access_token"])
    created = client.post(
        "/api/projects",
        headers=ha,
        json={"name": "PromptProj", "objective": "x"},
    )
    pid = created.json()["id"]
    res = client.post(
        f"/api/projects/{pid}/agent-prompt",
        headers=hb,
        json={"agent": "cursor", "force": True},
    )
    assert res.status_code == 404


def test_production_rejects_insecure_defaults():
    s = _settings(
        app_env="production",
        api_secret="real-api-secret-value",
        jwt_secret="dev-only-change-me-vibeprompt-jwt",
        credentials_encryption_key="prod-creds-key-32-chars-minimum!",
    )
    errors = s.validate_production_settings()
    assert any("JWT_SECRET" in e for e in errors)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        s.assert_secure_for_runtime()


def test_production_rejects_missing_api_secret():
    s = _settings(
        app_env="production",
        api_secret="",
        jwt_secret="prod-jwt-secret-key-32chars-min!",
        credentials_encryption_key="prod-creds-key-32-chars-minimum!",
    )
    errors = s.validate_production_settings()
    assert any("API_SECRET" in e for e in errors)
    with pytest.raises(RuntimeError, match="API_SECRET"):
        s.assert_secure_for_runtime()


def test_production_startup_fails_with_dev_defaults(monkeypatch: pytest.MonkeyPatch):
    settings = _settings(
        app_env="production",
        api_secret="",
        jwt_secret="dev-only-change-me-vibeprompt-jwt",
        credentials_encryption_key="dev-only-change-me-vibeprompt-creds",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    from app.main import create_app

    app = create_app()
    with pytest.raises(RuntimeError, match="insecure configuration"):
        with TestClient(app):
            pass
    get_settings.cache_clear()


def test_production_api_rejects_missing_api_secret_header(tmp_db: str):
    settings = _settings(
        app_env="production",
        api_secret="super-secret-api-token",
        jwt_secret="prod-jwt-secret-key-32chars-min!",
        credentials_encryption_key="prod-creds-key-32-chars-minimum!",
    )
    repo = SQLiteProjectRepository(tmp_db)
    client, _, _ = _build_client(settings, repo=repo, db_path=tmp_db)

    # No X-API-Secret
    res = client.get("/api/health")
    assert res.status_code == 401

    # Wrong secret
    res = client.get("/api/health", headers={"X-API-Secret": "wrong"})
    assert res.status_code == 401

    # Correct secret
    res = client.get("/api/health", headers={"X-API-Secret": "super-secret-api-token"})
    assert res.status_code == 200


def test_production_requires_auth_for_projects(tmp_db: str):
    secret = "super-secret-api-token"
    settings = _settings(
        app_env="production",
        api_secret=secret,
        jwt_secret="prod-jwt-secret-key-32chars-min!",
        credentials_encryption_key="prod-creds-key-32-chars-minimum!",
    )
    repo = SQLiteProjectRepository(tmp_db)
    client, _, _ = _build_client(settings, repo=repo, db_path=tmp_db)
    headers = {"X-API-Secret": secret}

    unauth = client.get("/api/projects", headers=headers)
    assert unauth.status_code == 401

    user = client.post(
        "/api/auth/register",
        headers=headers,
        json={"email": "prod@example.com", "password": "password123"},
    )
    assert user.status_code == 200
    token = user.json()["access_token"]
    auth = {**headers, "Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/projects",
        headers=auth,
        json={"name": "ProdProj", "objective": "ok"},
    )
    assert created.status_code == 200


def test_development_anonymous_unowned_still_works():
    """Local convenience: unowned projects remain usable without auth."""
    settings = _settings(app_env="development", api_secret="")
    client, _, _ = _build_client(settings)
    created = client.post("/api/projects", json={"name": "Local", "objective": "dev"})
    assert created.status_code == 200
    pid = created.json()["id"]
    got = client.get(f"/api/projects/{pid}")
    assert got.status_code == 200


def test_authorization_unit_free_tier_false_still_enforces_owner():
    from app.auth.authorization import assert_project_access
    from app.auth.models import UserRecord
    from datetime import datetime, timezone
    from fastapi import HTTPException
    from app.projects.models import ProjectState

    repo = InMemoryProjectRepository()
    p = repo.create(ProjectState(name="Owned"), owner_id="user_a")
    settings = _settings(free_tier_enabled=False, app_env="development")
    user_b = UserRecord(
        id="user_b", email="b@example.com", created_at=datetime.now(timezone.utc)
    )
    with pytest.raises(HTTPException) as exc:
        assert_project_access(repo, p.id, user_b, settings)
    assert exc.value.status_code == 404
