"""Platform-funded Qwen free tier + BYOK routing tests (mocked providers)."""

from __future__ import annotations

import asyncio
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.security import hash_password
from app.config import Settings, get_settings
from app.credentials.encryption import CredentialCipher
from app.free_tier.models import FundingSource
from app.inference.router import (
    InferenceRouteError,
    InferenceRouteErrorCode,
    resolve_inference,
)
from app.orchestration.engine import FreeTierExhaustedError, GrillEngine
from app.persistence.repository import InMemoryProjectRepository
from app.persistence.user_store import UserStore
from app.projects.models import ProjectState
from app.providers.base import PrimaryAnalysis, ProviderError, ProviderErrorKind
from app.providers.mock import MockProvider, heuristic_primary


@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    return str(tmp_path / "free_tier.db")


@pytest.fixture
def store(tmp_db: str) -> UserStore:
    return UserStore(tmp_db)


@pytest.fixture
def settings_free() -> Settings:
    get_settings.cache_clear()
    return Settings(
        free_tier_enabled=True,
        free_tier_generations=20,
        free_tier_provider="qwen",
        free_tier_model="qwen-plus",
        qwen_api_key="platform-qwen-key",
        qwen_base_url="https://example.test/v1",
        jwt_secret="test-jwt-secret-key-32bytes-min!!",
        credentials_encryption_key="test-creds-encryption-key-32b!!",
        gemini_api_key="",
        groq_api_key="",
        openrouter_api_key="",
        critic_enabled=False,
        database_path="./data/test-free.db",
    )


def _register(client: TestClient, email: str = "user@example.com") -> dict:
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
def free_client(store: UserStore, settings_free: Settings, tmp_db: str):
    get_settings.cache_clear()
    settings_free.database_path = tmp_db

    from app.api import deps
    from app.main import create_app
    from app.providers.mock import MockProvider

    primary = MockProvider(primary_handler=heuristic_primary)
    repo = InMemoryProjectRepository()

    def _engine() -> GrillEngine:
        return GrillEngine(
            repo=repo,
            primary=primary,
            critic=None,
            settings=settings_free,
            using_offline_primary=False,
            user_store=store,
        )

    app = create_app()
    app.dependency_overrides[deps.get_repository] = lambda: repo
    app.dependency_overrides[deps.get_user_store] = lambda: store
    app.dependency_overrides[deps.get_engine] = _engine
    from app.config import get_settings as cfg_get

    app.dependency_overrides[cfg_get] = lambda: settings_free

    with TestClient(app) as c:
        yield c, repo, store, settings_free, primary

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_01_new_user_gets_exactly_20(free_client):
    client, _, store, settings, _ = free_client
    data = _register(client)
    user_id = data["user"]["id"]
    alloc = store.get_free_tier_allocation(user_id)
    assert alloc is not None
    assert alloc["generations_allocated"] == 20
    assert alloc["generations_used"] == 0

    status = client.get(
        "/api/free-tier/status",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert status.status_code == 200
    body = status.json()
    assert body["remaining"] == 20
    assert body["allocated"] == 20
    assert body["funding"] == "PLATFORM"


def test_02_returning_user_no_second_allocation(free_client):
    client, _, store, settings, _ = free_client
    data = _register(client)
    user_id = data["user"]["id"]
    store.ensure_free_tier_allocation(
        user_id,
        generations=999,
        provider="qwen",
        model="qwen-plus",
    )
    alloc = store.get_free_tier_allocation(user_id)
    assert alloc["generations_allocated"] == 20  # original wins

    login = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    alloc2 = store.get_free_tier_allocation(user_id)
    assert alloc2["generations_allocated"] == 20


def test_03_successful_generation_consumes_one(free_client):
    client, repo, store, settings, _ = free_client
    data = _register(client)
    token = data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Force a non-conversation-only message by creating project then messaging.
    created = client.post(
        "/api/projects",
        json={"name": "App", "objective": "Build notes"},
        headers=headers,
    )
    assert created.status_code == 200
    pid = created.json()["id"]

    # Patch resolve to use mock primary under PLATFORM funding path via engine wiring:
    # Engine resolves real qwen; mock the resolve_inference to return our mock.
    from app.inference.router import ResolvedInference
    from app.orchestration import engine as engine_mod
    from app.providers.mock import MockProvider

    mock = MockProvider(primary_handler=heuristic_primary)

    def fake_resolve(**kwargs):
        return ResolvedInference(
            primary=mock,
            critic=None,
            funding_source=FundingSource.PLATFORM,
            provider="qwen",
            model="qwen-plus",
        )

    with patch.object(engine_mod, "resolve_inference", side_effect=fake_resolve):
        res = client.post(
            f"/api/projects/{pid}/messages",
            json={
                "content": "We'll use Kubernetes and microservices for a solo notes app by Friday."
            },
            headers=headers,
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["funding_source"] == "PLATFORM"
    assert body["free_tier"]["used"] == 1
    assert body["free_tier"]["remaining"] == 19


def test_04_failed_generation_does_not_consume(store: UserStore, settings_free: Settings):
    user = store.create_user(email="a@b.com", password_hash=hash_password("password123"))
    store.ensure_free_tier_allocation(
        user.id,
        generations=20,
        provider="qwen",
        model="qwen-plus",
    )
    gen_id = store.reserve_platform_generation(
        user.id, provider="qwen", model="qwen-plus"
    )
    alloc = store.get_free_tier_allocation(user.id)
    assert alloc["generations_used"] == 1

    store.complete_generation(
        gen_id,
        success=False,
        error_message="qwen down",
        release_reservation=True,
    )
    alloc = store.get_free_tier_allocation(user.id)
    assert alloc["generations_used"] == 0


def test_05_concurrent_requests_cannot_overspend(store: UserStore):
    user = store.create_user(email="c@d.com", password_hash=hash_password("password123"))
    store.ensure_free_tier_allocation(
        user.id,
        generations=2,
        provider="qwen",
        model="qwen-plus",
    )

    results: list[str | Exception] = []

    def attempt(_: int) -> str:
        return store.reserve_platform_generation(
            user.id, provider="qwen", model="qwen-plus"
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(attempt, i) for i in range(8)]
        for f in futures:
            try:
                results.append(f.result())
            except Exception as exc:  # noqa: BLE001
                results.append(exc)

    successes = [r for r in results if isinstance(r, str)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 2
    assert len(failures) == 6
    alloc = store.get_free_tier_allocation(user.id)
    assert alloc["generations_used"] == 2


def test_06_byok_uses_user_provider(store: UserStore, settings_free: Settings):
    user = store.create_user(email="byok@ex.com", password_hash=hash_password("password123"))
    store.ensure_free_tier_allocation(
        user.id, generations=20, provider="qwen", model="qwen-plus"
    )
    cipher = CredentialCipher(settings_free.credentials_encryption_key)
    store.upsert_provider_config(
        user.id,
        provider="groq",
        model="llama-test",
        encrypted_api_key=cipher.encrypt("user-groq-key"),
        base_url=None,
        set_active=True,
    )
    resolved = resolve_inference(
        settings=settings_free, store=store, user_id=user.id
    )
    assert resolved.funding_source == FundingSource.BYOK
    assert resolved.provider == "groq"
    assert resolved.model == "llama-test"


def test_07_exhausted_prompts_byok(free_client):
    client, _, store, settings, _ = free_client
    data = _register(client)
    user_id = data["user"]["id"]
    # Exhaust
    for _ in range(20):
        gid = store.reserve_platform_generation(
            user_id, provider="qwen", model="qwen-plus"
        )
        store.complete_generation(gid, success=True)

    status = client.get(
        "/api/free-tier/status",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    ).json()
    assert status["exhausted"] is True
    assert status["requires_byok"] is True
    assert status["remaining"] == 0

    created = client.post(
        "/api/projects",
        json={"name": "X"},
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    pid = created.json()["id"]
    res = client.post(
        f"/api/projects/{pid}/messages",
        json={"content": "Use Redis for everything by tomorrow with payments."},
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert res.status_code == 402
    detail = res.json()["detail"]
    assert detail["code"] == "free_tier_exhausted"


def test_08_byok_works_after_exhaustion(store: UserStore, settings_free: Settings):
    user = store.create_user(email="e@f.com", password_hash=hash_password("password123"))
    store.ensure_free_tier_allocation(
        user.id, generations=1, provider="qwen", model="qwen-plus"
    )
    gid = store.reserve_platform_generation(user.id, provider="qwen", model="qwen-plus")
    store.complete_generation(gid, success=True)

    with pytest.raises(InferenceRouteError) as exc:
        resolve_inference(settings=settings_free, store=store, user_id=user.id)
    assert exc.value.code == InferenceRouteErrorCode.FREE_TIER_EXHAUSTED

    cipher = CredentialCipher(settings_free.credentials_encryption_key)
    store.upsert_provider_config(
        user.id,
        provider="qwen",
        model="qwen-plus",
        encrypted_api_key=cipher.encrypt("user-key"),
        base_url=None,
        set_active=True,
    )
    resolved = resolve_inference(
        settings=settings_free, store=store, user_id=user.id
    )
    assert resolved.funding_source == FundingSource.BYOK


def test_09_qwen_failure_useful_error(free_client):
    client, _, store, settings, _ = free_client
    data = _register(client)
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    pid = client.post("/api/projects", json={"name": "Y"}, headers=headers).json()["id"]

    from app.inference.router import ResolvedInference
    from app.orchestration import engine as engine_mod
    from app.providers.base import ModelProvider

    class FailingProvider(ModelProvider):
        name = "qwen"

        def is_available(self) -> bool:
            return True

        async def analyze_primary(self, **kwargs):
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "Qwen 503")

        async def critique(self, **kwargs):
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "Qwen 503")

    def fake_resolve(**kwargs):
        return ResolvedInference(
            primary=FailingProvider(),
            critic=None,
            funding_source=FundingSource.PLATFORM,
            provider="qwen",
            model="qwen-plus",
        )

    with patch.object(engine_mod, "resolve_inference", side_effect=fake_resolve):
        res = client.post(
            f"/api/projects/{pid}/messages",
            json={"content": "Ship a marketplace with AI agents by next week."},
            headers=headers,
        )
    assert res.status_code == 503
    assert "Qwen" in res.json()["detail"]["message"] or "unavailable" in res.json()[
        "detail"
    ]["message"].lower()
    alloc = store.get_free_tier_allocation(data["user"]["id"])
    assert alloc["generations_used"] == 0


def test_10_existing_legacy_mode_still_works(client):
    """FREE_TIER_ENABLED=false path — existing API client fixture."""
    res = client.post("/api/projects", json={"name": "Legacy"})
    assert res.status_code == 200
    pid = res.json()["id"]
    msg = client.post(
        f"/api/projects/{pid}/messages",
        json={"content": "hello"},
    )
    assert msg.status_code == 200


def test_admin_config_hides_qwen_key(free_client):
    client, _, _, _, _ = free_client
    res = client.get("/api/admin/free-tier-config")
    assert res.status_code == 200
    body = res.json()
    assert "qwen_api_key" not in body
    assert "api_key" not in str(body).lower() or body.get("platform_key_configured") is True
    assert body["enabled"] is True
    assert body["generations"] == 20


def test_byok_list_never_returns_key(free_client):
    client, _, store, settings, _ = free_client
    data = _register(client)
    cipher = CredentialCipher(settings.credentials_encryption_key)
    store.upsert_provider_config(
        data["user"]["id"],
        provider="groq",
        model="x",
        encrypted_api_key=cipher.encrypt("super-secret-key"),
        base_url=None,
        set_active=True,
    )
    res = client.get(
        "/api/byok",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert res.status_code == 200
    payload = res.text.lower()
    assert "super-secret-key" not in payload
    assert res.json()[0]["has_api_key"] is True


def test_health_never_leaks_keys(free_client):
    client, _, _, _, _ = free_client
    body = client.get("/api/health").text.lower()
    assert "platform-qwen-key" not in body
    assert "api_key" not in body or "configured" in body
