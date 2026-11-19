"""Pre-launch security hardening regressions."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.knowledge.files import FileValidationError, ensure_under_root, safe_filename
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
        free_tier_enabled=True,
        critic_enabled=False,
        review_intensity="normal",
        database_path="./data/test_sec_audit.db",
        api_secret="server-only-secret-not-for-spa-32b",
        app_env="production",
        jwt_secret="test-jwt-secret-key-32bytes-min!!",
        credentials_encryption_key="test-creds-encryption-key-32b!!",
        cors_origins="https://app.example.com",
        guest_mint_rate_limit_per_hour=20,
        guest_free_tier_generations=5,
    )
    base.update(kwargs)
    return Settings(**base)


def _client(settings: Settings, db_path: str) -> TestClient:
    get_settings.cache_clear()
    from app.api import deps
    from app.main import create_app
    from app.orchestration.engine import GrillEngine

    repo = SQLiteProjectRepository(db_path)
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

    app = create_app(settings)
    app.dependency_overrides[deps.get_repository] = lambda: repo
    app.dependency_overrides[deps.get_settings] = lambda: settings
    app.dependency_overrides[deps.get_engine] = _engine
    app.dependency_overrides[deps.get_user_store] = lambda: store
    from app.config import get_settings as cfg_get

    app.dependency_overrides[cfg_get] = lambda: settings
    return TestClient(app)


def test_cross_guest_bola_isolation():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "a.db")
        settings = _settings(database_path=db, free_tier_enabled=False)
        # free_tier off but production still requires auth
        client = _client(settings, db)

        g1 = client.post("/api/auth/guest").json()
        g2 = client.post("/api/auth/guest").json()
        h1 = {"Authorization": f"Bearer {g1['access_token']}"}
        h2 = {"Authorization": f"Bearer {g2['access_token']}"}

        created = client.post(
            "/api/projects",
            headers=h1,
            json={"name": "GuestA", "objective": "private"},
        )
        assert created.status_code == 200, created.text
        pid = created.json()["id"]

        assert client.get(f"/api/projects/{pid}", headers=h2).status_code == 404
        assert (
            client.post(
                f"/api/projects/{pid}/messages",
                headers=h2,
                json={"content": "hijack"},
            ).status_code
            == 404
        )
        assert client.delete(f"/api/projects/{pid}", headers=h2).status_code == 404
        assert client.get(f"/api/projects/{pid}", headers=h1).status_code == 200


def test_oversized_chat_payload_rejected_with_422():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "a.db")
        settings = _settings(database_path=db, free_tier_enabled=False)
        client = _client(settings, db)
        token = client.post("/api/auth/guest").json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post(
            "/api/projects",
            headers=headers,
            json={"name": "Bound", "objective": "x"},
        )
        pid = created.json()["id"]
        huge = "x" * 20_000
        res = client.post(
            f"/api/projects/{pid}/messages",
            headers=headers,
            json={"content": huge},
        )
        assert res.status_code == 422


def test_production_rejects_weak_secrets_and_cors_wildcard():
    weak = _settings(
        jwt_secret="short-secret",
        credentials_encryption_key="also-short",
        cors_origins="*",
    )
    errors = weak.validate_production_settings()
    assert any("JWT_SECRET" in e for e in errors)
    assert any("CREDENTIALS_ENCRYPTION_KEY" in e for e in errors)
    assert any("wildcard" in e.lower() or "*" in e for e in errors)

    aliased = _settings(
        jwt_secret="same-secret-value-32-characters-ok!!",
        credentials_encryption_key="same-secret-value-32-characters-ok!!",
    )
    assert any("must not equal JWT_SECRET" in e for e in aliased.validate_production_settings())


def test_production_disables_openapi_and_sets_security_headers():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "a.db")
        settings = _settings(database_path=db, free_tier_enabled=False)
        client = _client(settings, db)
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.headers.get("x-content-type-options") == "nosniff"
        assert health.headers.get("x-frame-options") == "DENY"
        assert (
            health.headers.get("referrer-policy")
            == "strict-origin-when-cross-origin"
        )


def test_path_traversal_rejected_by_ensure_under_root(tmp_path: Path):
    root = tmp_path / "uploads"
    root.mkdir()
    (root / "ok.txt").write_text("hi", encoding="utf-8")
    assert ensure_under_root(root / "ok.txt", root).is_file()

    with pytest.raises(FileValidationError, match="escapes"):
        ensure_under_root(tmp_path / ".." / "etc" / "passwd", root)

    with pytest.raises(FileValidationError, match="escapes"):
        ensure_under_root(Path("/etc/passwd"), root)

    # Basename stripping still blocks traversal in filenames
    assert ".." not in safe_filename("../../etc/passwd.txt")
    assert safe_filename("../../etc/passwd.txt").endswith(".txt")


def test_byok_list_never_returns_api_key():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "a.db")
        settings = _settings(database_path=db, free_tier_enabled=False)
        client = _client(settings, db)
        # Register a real user for BYOK
        reg = client.post(
            "/api/auth/register",
            json={"email": "byok@example.com", "password": "password12345"},
        )
        assert reg.status_code == 200, reg.text
        token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        listed = client.get("/api/byok", headers=headers)
        assert listed.status_code == 200
        for row in listed.json():
            assert "api_key" not in row
            assert "encrypted_api_key" not in row
