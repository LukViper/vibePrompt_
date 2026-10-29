"""Provider failure modes (scenarios 11–14)."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.providers.base import (
    CriticFindingAction,
    CriticReview,
    PrimaryAnalysis,
    ProviderError,
    ProviderErrorKind,
    StatePatch,
)
from app.providers.mock import MockProvider
from tests.conftest import build_engine, make_finding


@pytest.mark.asyncio
async def test_11_primary_timeout_falls_back(repo, settings, project):
    primary = MockProvider(
        primary_error=ProviderError(ProviderErrorKind.TIMEOUT, "primary timed out")
    )
    engine = build_engine(repo, settings, primary=primary, offline=False)
    res = await engine.handle_message(
        project.id,
        "Build a marketplace platform by tomorrow with payments and chat.",
    )
    assert res.message.content
    assert any("timeout" in x.lower() or "Primary" in x for x in res.review_limitations)


@pytest.mark.asyncio
async def test_11b_primary_rate_limit_falls_back(repo, settings, project):
    primary = MockProvider(
        primary_error=ProviderError(ProviderErrorKind.RATE_LIMIT, "primary rate limited")
    )
    engine = build_engine(repo, settings, primary=primary, offline=False)
    res = await engine.handle_message(
        project.id,
        "Simple personal todo app with Kubernetes and Kafka microservices.",
    )
    assert any("rate_limit" in x.lower() or "Primary" in x for x in res.review_limitations)


@pytest.mark.asyncio
async def test_12_critic_timeout_continues_primary_only(repo, settings, project):
    project.objective = "App"
    project.intended_users = ["u"]
    repo.save(project)

    def primary(**_):
        return PrimaryAnalysis(
            reply="Concern raised.",
            intent="architecture_decision",
            findings=[make_finding(severity="high")],
            state_patch=StatePatch(),
        )

    call_log: list[str] = []
    critic = MockProvider(
        critic_error=ProviderError(ProviderErrorKind.TIMEOUT, "critic timed out"),
        call_log=call_log,
    )
    engine = build_engine(
        repo,
        settings,
        primary=MockProvider(primary_handler=primary, call_log=call_log),
        critic=critic,
        offline=False,
    )
    res = await engine.handle_message(project.id, "We will use microservices architecture.")
    assert "critic" in call_log
    assert any("critic" in x.lower() for x in res.review_limitations)
    assert res.message.provenance.value == "primary_only"
    assert res.findings  # findings preserved from primary


@pytest.mark.asyncio
async def test_12b_critic_rate_limit(repo, settings, project):
    project.objective = "App"
    repo.save(project)

    def primary(**_):
        return PrimaryAnalysis(
            reply="Concern.",
            intent="scope_change",
            findings=[make_finding(severity="critical")],
            state_patch=StatePatch(),
        )

    engine = build_engine(
        repo,
        settings,
        primary=MockProvider(primary_handler=primary),
        critic=MockProvider(
            critic_error=ProviderError(ProviderErrorKind.RATE_LIMIT, "critic rate limited")
        ),
        offline=False,
    )
    res = await engine.handle_message(project.id, "Deadline is this week for the full platform.")
    assert any("rate" in x.lower() or "critic" in x.lower() for x in res.review_limitations)


@pytest.mark.asyncio
async def test_13_both_providers_unavailable(repo, settings, project):
    primary = MockProvider(
        available=False,
        primary_error=ProviderError(ProviderErrorKind.UNAVAILABLE, "down"),
    )
    critic = MockProvider(
        available=False,
        critic_error=ProviderError(ProviderErrorKind.UNAVAILABLE, "down"),
    )
    engine = build_engine(repo, settings, primary=primary, critic=critic, offline=False)
    res = await engine.handle_message(
        project.id,
        "Build Uber-for-dogs marketplace by tomorrow.",
    )
    # Heuristic fallback still produces useful review
    assert res.message.content
    assert res.review_limitations


@pytest.mark.asyncio
async def test_14_no_api_keys_configured(settings):
    assert settings.primary_configured is False
    assert settings.critic_configured is False
    from app.providers.factory import build_providers
    from app.providers.failover import FailoverPrimaryProvider

    bundle = build_providers(settings)
    assert bundle.using_offline_primary is True
    assert isinstance(bundle.primary, FailoverPrimaryProvider)
    assert bundle.primary.is_available() is True  # offline fallback always ready
    assert bundle.critic is None
