"""Guest JWT + free-tier abuse controls — no static SPA API secret."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.persistence.repository import InMemoryProjectRepository
from app.persistence.user_store import UserStore
from app.providers.mock import MockProvider, heuristic_primary


def _settings(**kwargs) -> Settings:
    get_settings.cache_clear()
    base = dict(
        gemini_api_key="",
        openrouter_api_key="",
        groq_api_key="",
        qwen_api_key="platform-qwen-test-key",
        free_tier_enabled=True,
        critic_enabled=False,
        review_intensity="normal",
        database_path="./data/test_guest.db",
        api_secret="server-only-secret-not-for-spa",
        app_env="production",
        jwt_secret="test-jwt-secret-key-32bytes-min!!",
        credentials_encryption_key="test-creds-encryption-key-32b!!",
        guest_free_tier_generations=3,
        guest_rate_limit_per_minute=30,
        guest_mint_rate_limit_per_hour=50,
        qwen_global_daily_request_cap=2,
        free_tier_generations=3,
    )
    base.update(kwargs)
    return Settings(**base)


def _client(settings: Settings, db_path: str) -> TestClient:
    get_settings.cache_clear()
    from app.api import deps
    from app.main import create_app
    from app.orchestration.engine import GrillEngine

    repo = InMemoryProjectRepository()
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
    app.dependency_overrides[deps.get_user_store] = lambda: store
    from app.config import get_settings as cfg_get

    app.dependency_overrides[cfg_get] = lambda: settings
    return TestClient(app)


def test_unauthenticated_project_list_fails_in_production():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "g.db")
        settings = _settings(database_path=db)
        client = _client(settings, db)
        res = client.get("/api/projects")
        assert res.status_code == 401


def test_guest_jwt_mints_without_api_secret_and_enforces_caps():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "g.db")
        settings = _settings(database_path=db)
        client = _client(settings, db)

        # No X-API-Secret — guest mint is a public bootstrap route
        minted = client.post("/api/auth/guest")
        assert minted.status_code == 200, minted.text
        body = minted.json()
        assert body["role"] == "guest"
        assert body["generations_allocated"] == 3
        token = body["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Guest can create a project without static API secret
        created = client.post(
            "/api/projects",
            headers=headers,
            json={"name": "Guest Project", "objective": "beta"},
        )
        assert created.status_code == 200, created.text
        project_id = created.json()["id"]

        # Exhaust guest free generations via message path (platform funding)
        # Global daily cap is 2 — third platform-funded call should 429
        statuses = []
        for i in range(4):
            res = client.post(
                f"/api/projects/{project_id}/messages",
                headers=headers,
                json={"content": f"Please review go-live plan number {i} carefully."},
            )
            statuses.append(res.status_code)
            if res.status_code == 429:
                detail = res.json().get("detail") or {}
                assert detail.get("code") in {
                    "rate_limited",
                    "free_tier_exhausted",
                    "byok_required",
                }
                break
        assert 429 in statuses or 402 in statuses


def test_vite_api_secret_absent_from_frontend_sources():
    root = Path(__file__).resolve().parents[2] / "frontend"
    offenders: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if "node_modules" in path.parts or "dist" in path.parts:
            continue
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx", ".env", ".example", ".md"}:
            continue
        # .env.example may mention the name while forbidding it — allow docs that say Do NOT
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "VITE_API_SECRET" in text:
            if path.name == ".env.example" and "Do NOT" in text:
                continue
            if "VITE_API_SECRET" in text and "import.meta.env.VITE_API_SECRET" in text:
                offenders.append(str(path))
            elif path.suffix in {".ts", ".tsx", ".js", ".jsx"}:
                offenders.append(str(path))
    assert offenders == [], f"VITE_API_SECRET still referenced in: {offenders}"
