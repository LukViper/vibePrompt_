"""Sybil mint limits + trusted-proxy IP extraction for guest sessions."""

from __future__ import annotations

import tempfile
from pathlib import Path
from fastapi import Request
from fastapi.testclient import TestClient

from app.auth.client_ip import hash_client_ip, resolve_client_ip
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
        database_path="./data/test_guest_sybil.db",
        api_secret="server-only-secret-not-for-spa",
        app_env="production",
        jwt_secret="test-jwt-secret-key-32bytes-min!!",
        credentials_encryption_key="test-creds-encryption-key-32b!!",
        guest_free_tier_generations=2,
        guest_rate_limit_per_minute=60,
        guest_mint_rate_limit_per_hour=3,
        guest_ip_daily_generations=2,
        qwen_global_daily_request_cap=100,
        free_tier_generations=20,
        trusted_proxy_cidrs="",
    )
    base.update(kwargs)
    return Settings(**base)


def _client(settings: Settings, db_path: str) -> tuple[TestClient, UserStore]:
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
    return TestClient(app), store


def test_guest_mint_rate_limit_per_ip_returns_429():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "s.db")
        settings = _settings(database_path=db, guest_mint_rate_limit_per_hour=3)
        client, _ = _client(settings, db)

        codes = [client.post("/api/auth/guest").status_code for _ in range(4)]
        assert codes[:3] == [200, 200, 200]
        assert codes[3] == 429
        detail = client.post("/api/auth/guest").json().get("detail") or {}
        assert detail.get("code") == "guest_mint_rate_limited"


def test_rotating_guest_jwts_share_ip_inference_quota():
    from unittest.mock import patch

    from app.free_tier.models import FundingSource
    from app.inference.router import ResolvedInference
    from app.providers.mock import MockProvider, heuristic_primary

    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "s.db")
        settings = _settings(
            database_path=db,
            guest_mint_rate_limit_per_hour=10,
            guest_ip_daily_generations=2,
            guest_free_tier_generations=10,
            qwen_global_daily_request_cap=100,
        )
        client, store = _client(settings, db)

        body1 = client.post("/api/auth/guest").json()
        body2 = client.post("/api/auth/guest").json()
        t1 = body1["access_token"]
        t2 = body2["access_token"]

        # Confirm both sessions share the same ip_hash (TestClient peer)
        s1 = store.get_guest_session(body1["user"]["id"])
        s2 = store.get_guest_session(body2["user"]["id"])
        assert s1 and s2
        assert s1["ip_hash"] == s2["ip_hash"]
        assert s1["ip_hash"]

        mock_primary = MockProvider(primary_handler=heuristic_primary)

        def _fake_resolve(**_kwargs):
            return ResolvedInference(
                primary=mock_primary,
                critic=None,
                funding_source=FundingSource.PLATFORM,
                provider="qwen",
                model="mock",
                using_offline_primary=True,
            )

        def _chat(token: str, n: int) -> int:
            h = {"Authorization": f"Bearer {token}"}
            created = client.post(
                "/api/projects",
                headers=h,
                json={"name": f"P{n}", "objective": "beta"},
            )
            assert created.status_code == 200, created.text
            pid = created.json()["id"]
            res = client.post(
                f"/api/projects/{pid}/messages",
                headers=h,
                json={"content": f"Please review architecture decision {n} carefully."},
            )
            return res.status_code

        with patch("app.orchestration.engine.resolve_inference", side_effect=_fake_resolve):
            assert _chat(t1, 1) == 200
            assert _chat(t2, 2) == 200
            # Third generation from either JWT hits shared IP daily cap
            third = _chat(t1, 3)
            assert third == 429


def test_spoofed_x_forwarded_for_ignored_without_trusted_proxy():
    settings = _settings(trusted_proxy_cidrs="")

    class _Client:
        host = "203.0.113.10"

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"x-forwarded-for", b"198.51.100.50")],
        "client": ("203.0.113.10", 12345),
        "server": ("test", 80),
    }
    request = Request(scope)
    assert resolve_client_ip(request, settings) == "203.0.113.10"
    assert hash_client_ip("203.0.113.10") != hash_client_ip("198.51.100.50")


def test_trusted_proxy_honors_forwarded_ip_when_peer_trusted():
    settings = _settings(trusted_proxy_cidrs="10.0.0.0/8")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [
            (b"x-forwarded-for", b"198.51.100.50, 10.0.0.2"),
        ],
        "client": ("10.0.0.2", 12345),
        "server": ("test", 80),
    }
    request = Request(scope)
    assert resolve_client_ip(request, settings) == "198.51.100.50"


def test_untrusted_peer_cannot_spoof_via_cf_connecting_ip():
    settings = _settings(trusted_proxy_cidrs="10.0.0.0/8")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"cf-connecting-ip", b"198.51.100.50")],
        "client": ("203.0.113.10", 12345),  # not in trusted CIDR
        "server": ("test", 80),
    }
    request = Request(scope)
    assert resolve_client_ip(request, settings) == "203.0.113.10"
