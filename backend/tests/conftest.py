"""Shared fixtures — all tests run without real API credentials."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)
os.environ["CRITIC_ENABLED"] = "true"
os.environ["REVIEW_INTENSITY"] = "normal"

from app.config import Settings, get_settings
from app.orchestration.engine import GrillEngine
from app.persistence.repository import InMemoryProjectRepository
from app.projects.models import ProjectState
from app.providers.base import ModelProvider
from app.providers.mock import MockProvider, heuristic_primary


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return Settings(
        gemini_api_key="",
        groq_api_key="",
        critic_enabled=True,
        review_intensity="normal",
        database_path="./data/test.db",
        api_secret="",
    )


@pytest.fixture
def repo() -> InMemoryProjectRepository:
    return InMemoryProjectRepository()


@pytest.fixture
def project(repo: InMemoryProjectRepository) -> ProjectState:
    p = ProjectState(name="Test Project", objective="")
    return repo.create(p)


def make_finding(
    *,
    title: str = "Concern",
    claim: str = "A claim",
    severity: str = "high",
    confidence: float = 0.8,
):
    from app.providers.base import CandidateFinding

    return CandidateFinding(
        title=title,
        challenged_claim=claim,
        reasoning="Because of X",
        evidence=["Project context fact"],
        assumptions_to_verify=["Assumption A"],
        severity=severity,
        confidence=confidence,
        potential_impact="Wasted effort",
        recommended_next_step="Clarify scope",
        invalidation_criteria="Evidence that invalidates",
    )


def build_engine(
    repo: InMemoryProjectRepository,
    settings: Settings,
    *,
    primary: ModelProvider | None = None,
    critic: ModelProvider | None = None,
    offline: bool = True,
) -> GrillEngine:
    return GrillEngine(
        repo=repo,
        primary=primary or MockProvider(primary_handler=heuristic_primary),
        critic=critic,
        settings=settings,
        using_offline_primary=offline,
    )


@pytest.fixture
def client(repo: InMemoryProjectRepository, settings: Settings):
    """API client with in-memory repo and heuristic primary via dependency overrides."""
    get_settings.cache_clear()

    from app.api import deps
    from app.main import create_app

    primary = MockProvider(primary_handler=heuristic_primary)

    def _engine() -> GrillEngine:
        return GrillEngine(
            repo=repo,
            primary=primary,
            critic=None,
            settings=settings,
            using_offline_primary=True,
        )

    app = create_app()
    app.dependency_overrides[deps.get_repository] = lambda: repo
    app.dependency_overrides[deps.get_settings] = lambda: settings
    app.dependency_overrides[deps.get_engine] = _engine
    # Health endpoint uses get_settings via Depends
    from app.config import get_settings as cfg_get_settings

    app.dependency_overrides[cfg_get_settings] = lambda: settings

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    get_settings.cache_clear()
