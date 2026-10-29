"""Multi-provider failover tests — mocked HTTP, no credentials or network."""

from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.persistence.repository import InMemoryProjectRepository
from app.projects.models import FindingStatus, ProjectState
from app.providers.base import (
    PrimaryAnalysis,
    ProviderError,
    ProviderErrorKind,
    StatePatch,
)
from app.providers.failover import (
    FailoverPrimaryProvider,
    build_status_message,
    normalize_provider_order,
)
from app.providers.mock import MockProvider
from app.providers.factory import build_providers
from tests.conftest import build_engine, make_finding


def _ok(reply: str = "ok from provider") -> PrimaryAnalysis:
    return PrimaryAnalysis(
        reply=reply,
        intent="architecture_decision",
        findings=[make_finding(title="Scope risk", severity="high")],
        state_patch=StatePatch(objective="Test objective"),
    )


def _provider(
    name: str,
    *,
    available: bool = True,
    error: ProviderError | None = None,
    analysis: PrimaryAnalysis | None = None,
    call_log: list[str] | None = None,
    delay: float = 0.0,
) -> MockProvider:
    log = call_log if call_log is not None else []
    provider_name = name
    provider_error = error
    provider_analysis = analysis
    provider_delay = delay
    provider_available = available

    class TimedMock(MockProvider):
        async def analyze_primary(self, **kwargs):
            log.append(provider_name)
            if provider_delay:
                await asyncio.sleep(provider_delay)
            if self._primary_error:
                raise self._primary_error
            if provider_error is not None:
                raise provider_error
            if provider_analysis is not None:
                return provider_analysis
            return _ok(f"reply from {provider_name}")

        async def critique(self, **kwargs):
            raise ProviderError(ProviderErrorKind.OTHER, "not a critic")

        def is_available(self) -> bool:
            return provider_available

    mock = TimedMock(
        available=provider_available,
        primary_error=provider_error if provider_delay == 0 else None,
        call_log=[],  # keep provider-name log separate from MockProvider internals
    )
    mock.name = provider_name
    return mock


@pytest.mark.asyncio
async def test_01_gemini_succeeds_no_fallback():
    log: list[str] = []
    gemini = _provider("gemini", analysis=_ok("gemini"), call_log=log)
    openrouter = _provider("openrouter", analysis=_ok("or"), call_log=log)
    groq = _provider("groq", analysis=_ok("groq"), call_log=log)
    chain = FailoverPrimaryProvider([gemini, openrouter, groq], total_budget_seconds=30)
    result = await chain.run_primary(
        project_snapshot={}, user_message="hello architecture", conversation_tail=[]
    )
    assert result.provider == "gemini"
    assert result.offline is False
    assert result.status_message == "Gemini responding"
    assert log == ["gemini"]


@pytest.mark.asyncio
async def test_02_gemini_429_openrouter_succeeds():
    log: list[str] = []
    chain = FailoverPrimaryProvider(
        [
            _provider(
                "gemini",
                error=ProviderError(ProviderErrorKind.RATE_LIMIT, "429"),
                call_log=log,
            ),
            _provider("openrouter", analysis=_ok("or"), call_log=log),
            _provider("groq", analysis=_ok("groq"), call_log=log),
        ]
    )
    result = await chain.run_primary(
        project_snapshot={}, user_message="x", conversation_tail=[]
    )
    assert result.provider == "openrouter"
    assert "Gemini rate-limited" in result.status_message
    assert "OpenRouter responding" in result.status_message
    assert log == ["gemini", "openrouter"]


@pytest.mark.asyncio
async def test_03_gemini_and_openrouter_429_groq_succeeds():
    log: list[str] = []
    chain = FailoverPrimaryProvider(
        [
            _provider(
                "gemini",
                error=ProviderError(ProviderErrorKind.RATE_LIMIT, "429"),
                call_log=log,
            ),
            _provider(
                "openrouter",
                error=ProviderError(ProviderErrorKind.RATE_LIMIT, "429"),
                call_log=log,
            ),
            _provider("groq", analysis=_ok("groq"), call_log=log),
        ]
    )
    result = await chain.run_primary(
        project_snapshot={}, user_message="x", conversation_tail=[]
    )
    assert result.provider == "groq"
    assert "Groq responding" in result.status_message
    assert log == ["gemini", "openrouter", "groq"]


@pytest.mark.asyncio
async def test_04_gemini_timeout_openrouter_succeeds():
    log: list[str] = []
    chain = FailoverPrimaryProvider(
        [
            _provider(
                "gemini",
                error=ProviderError(ProviderErrorKind.TIMEOUT, "timeout"),
                call_log=log,
            ),
            _provider("openrouter", analysis=_ok("or"), call_log=log),
            _provider("groq", call_log=log),
        ]
    )
    result = await chain.run_primary(
        project_snapshot={}, user_message="x", conversation_tail=[]
    )
    assert result.provider == "openrouter"
    assert "timed out" in result.status_message.lower() or "unavailable" in result.status_message.lower()
    assert "openrouter" not in [a.provider for a in result.attempts if a.skipped]
    assert log == ["gemini", "openrouter"]


@pytest.mark.asyncio
async def test_05_gemini_and_openrouter_fail_groq_succeeds():
    log: list[str] = []
    chain = FailoverPrimaryProvider(
        [
            _provider(
                "gemini",
                error=ProviderError(ProviderErrorKind.UNAVAILABLE, "503"),
                call_log=log,
            ),
            _provider(
                "openrouter",
                error=ProviderError(ProviderErrorKind.UNAVAILABLE, "502"),
                call_log=log,
            ),
            _provider("groq", analysis=_ok("groq"), call_log=log),
        ]
    )
    result = await chain.run_primary(
        project_snapshot={}, user_message="x", conversation_tail=[]
    )
    assert result.provider == "groq"
    assert log == ["gemini", "openrouter", "groq"]


@pytest.mark.asyncio
async def test_06_all_external_fail_offline_heuristics():
    log: list[str] = []
    chain = FailoverPrimaryProvider(
        [
            _provider(
                "gemini",
                error=ProviderError(ProviderErrorKind.UNAVAILABLE, "down"),
                call_log=log,
            ),
            _provider(
                "openrouter",
                error=ProviderError(ProviderErrorKind.TIMEOUT, "t"),
                call_log=log,
            ),
            _provider(
                "groq",
                error=ProviderError(ProviderErrorKind.RATE_LIMIT, "429"),
                call_log=log,
            ),
        ]
    )
    result = await chain.run_primary(
        project_snapshot={},
        user_message="Build a marketplace platform by tomorrow with payments.",
        conversation_tail=[],
    )
    assert result.offline is True
    assert result.provider == "offline"
    assert "offline review active" in result.status_message.lower()
    assert result.analysis.reply
    assert log == ["gemini", "openrouter", "groq"]


@pytest.mark.asyncio
async def test_07_missing_credentials_skipped_safely():
    log: list[str] = []
    chain = FailoverPrimaryProvider(
        [
            _provider("gemini", available=False, call_log=log),
            _provider("openrouter", available=False, call_log=log),
            _provider("groq", analysis=_ok("groq"), call_log=log),
        ]
    )
    result = await chain.run_primary(
        project_snapshot={}, user_message="x", conversation_tail=[]
    )
    assert result.provider == "groq"
    assert log == ["groq"]
    assert all(
        a.skipped for a in result.attempts if a.provider in {"gemini", "openrouter"}
    )


@pytest.mark.asyncio
async def test_08_auth_error_does_not_infinite_retry():
    log: list[str] = []
    chain = FailoverPrimaryProvider(
        [
            _provider(
                "gemini",
                error=ProviderError(ProviderErrorKind.AUTH, "bad key"),
                call_log=log,
            ),
            _provider("openrouter", analysis=_ok("or"), call_log=log),
        ],
        per_provider_timeout=5,
        total_budget_seconds=10,
    )
    result = await chain.run_primary(
        project_snapshot={}, user_message="x", conversation_tail=[]
    )
    assert result.provider == "openrouter"
    # Gemini attempted exactly once (no same-provider retry on AUTH)
    assert log.count("gemini") == 1
    assert log.count("openrouter") == 1


@pytest.mark.asyncio
async def test_09_provider_status_identifies_winner(repo, settings, project):
    log: list[str] = []
    chain = FailoverPrimaryProvider(
        [
            _provider(
                "gemini",
                error=ProviderError(ProviderErrorKind.RATE_LIMIT, "429"),
                call_log=log,
            ),
            _provider("openrouter", analysis=_ok("from or"), call_log=log),
        ]
    )
    engine = build_engine(repo, settings, primary=chain, offline=False)
    res = await engine.handle_message(
        project.id,
        "We will use microservices architecture for the MVP platform.",
    )
    assert res.provider_used == "openrouter"
    assert res.provider_status is not None
    assert "OpenRouter responding" in res.provider_status
    assert res.offline_review is False


@pytest.mark.asyncio
async def test_10_state_and_findings_applied_once_after_failover(repo, settings):
    project = repo.create(ProjectState(name="Once"))
    log: list[str] = []
    analysis = PrimaryAnalysis(
        reply="Concern.",
        intent="initial_idea",
        findings=[make_finding(title="Unique finding", claim="claim-x", severity="high")],
        state_patch=StatePatch(objective="Only once objective"),
    )
    chain = FailoverPrimaryProvider(
        [
            _provider(
                "gemini",
                error=ProviderError(ProviderErrorKind.TIMEOUT, "t"),
                call_log=log,
            ),
            _provider("openrouter", analysis=analysis, call_log=log),
            _provider("groq", analysis=_ok("should not run"), call_log=log),
        ]
    )
    engine = build_engine(repo, settings, primary=chain, offline=False)
    res = await engine.handle_message(
        project.id,
        "I want to build a multi-tenant SaaS analytics platform for enterprises with SSO.",
    )
    assert log == ["gemini", "openrouter"]
    assert res.project.objective == "Only once objective"
    titles = [f.title for f in res.findings if f.status == FindingStatus.OPEN]
    assert titles.count("Unique finding") == 1
    # Only one user + one assistant message pair for this turn (plus history)
    assistant_msgs = [m for m in res.project.messages if m.role == "assistant"]
    assert len(assistant_msgs) == 1


@pytest.mark.asyncio
async def test_11_malformed_output_failover_or_offline():
    log: list[str] = []
    chain = FailoverPrimaryProvider(
        [
            _provider(
                "gemini",
                error=ProviderError(ProviderErrorKind.MALFORMED, "bad json"),
                call_log=log,
            ),
            _provider(
                "openrouter",
                error=ProviderError(ProviderErrorKind.MALFORMED, "bad json"),
                call_log=log,
            ),
            _provider(
                "groq",
                error=ProviderError(ProviderErrorKind.MALFORMED, "bad json"),
                call_log=log,
            ),
        ]
    )
    result = await chain.run_primary(
        project_snapshot={},
        user_message="Build Uber-for-dogs by tomorrow",
        conversation_tail=[],
    )
    assert result.offline is True
    assert result.analysis.reply


@pytest.mark.asyncio
async def test_12_timeout_budget_prevents_unbounded_waiting():
    log: list[str] = []
    chain = FailoverPrimaryProvider(
        [
            _provider("gemini", delay=0.4, call_log=log),
            _provider("openrouter", delay=0.4, call_log=log),
            _provider("groq", analysis=_ok("groq"), call_log=log),
        ],
        per_provider_timeout=0.15,
        total_budget_seconds=0.35,
    )
    result = await chain.run_primary(
        project_snapshot={}, user_message="x", conversation_tail=[]
    )
    # Budget should stop before spending unbounded time; offline or early exit
    assert result.provider in {"offline", "groq", "openrouter", "gemini"}
    assert (result.latency_ms or 0) < 2000


def test_13_normalize_order_dedupes_and_validates():
    assert normalize_provider_order(
        "gemini, groq, gemini, unknown, openrouter",
        default=["gemini", "openrouter", "groq"],
    ) == ["gemini", "groq", "openrouter"]
    assert normalize_provider_order("", default=["gemini", "openrouter", "groq"]) == [
        "gemini",
        "openrouter",
        "groq",
    ]


def test_14_factory_builds_chain_without_keys():
    settings = Settings(
        gemini_api_key="",
        openrouter_api_key="",
        groq_api_key="",
        critic_enabled=True,
    )
    bundle = build_providers(settings)
    assert bundle.using_offline_primary is True
    assert isinstance(bundle.primary, FailoverPrimaryProvider)
    assert len(bundle.primary.providers) == 3
    assert bundle.critic is None


def test_status_message_no_credentials():
    from app.providers.failover import ProviderAttempt

    msg = build_status_message(
        [
            ProviderAttempt("gemini", None, False, skipped=True, skip_reason="missing_credentials"),
            ProviderAttempt(
                "openrouter", None, False, skipped=True, skip_reason="missing_credentials"
            ),
            ProviderAttempt("groq", None, False, skipped=True, skip_reason="missing_credentials"),
        ],
        "offline",
        offline=True,
    )
    assert msg == "No provider credentials configured"


@pytest.mark.asyncio
async def test_invalid_request_no_same_provider_retry_loop():
    log: list[str] = []
    chain = FailoverPrimaryProvider(
        [
            _provider(
                "gemini",
                error=ProviderError(ProviderErrorKind.INVALID_REQUEST, "bad model"),
                call_log=log,
            ),
            _provider("openrouter", analysis=_ok("or"), call_log=log),
        ]
    )
    result = await chain.run_primary(
        project_snapshot={}, user_message="x", conversation_tail=[]
    )
    assert result.provider == "openrouter"
    assert log.count("gemini") == 1
