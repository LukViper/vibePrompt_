"""Regression tests for adversarial validation fixes (MT-1, CX, CI, CR)."""

from __future__ import annotations

import pytest

from app.compilation.agent_prompt import compile_agent_prompt
from app.config import Settings, get_settings
from app.grill.notes import apply_note_update, notes_conflict
from app.grill.offline_extract import extract_explicit_tech_and_rejections
from app.grill.policy import ReviewAction, decide_review_policy
from app.grill.tech import (
    apply_technology_tokens,
    parse_technology_token,
    stack_from_selections,
)
from app.orchestration.engine import GrillEngine
from app.persistence.repository import InMemoryProjectRepository
from app.projects.models import Decision, MessageIntent, ProjectState, RejectedApproach
from app.projects.state_apply import apply_state_patch
from app.providers.base import (
    GenerationSettings,
    PrimaryAnalysis,
    ProviderError,
    ProviderErrorKind,
    StatePatch,
)
from app.providers.mock import MockProvider, heuristic_primary
from app.grill.modes import BehaviouralMode


def _settings(**kwargs) -> Settings:
    get_settings.cache_clear()
    base = dict(
        gemini_api_key="",
        openrouter_api_key="",
        groq_api_key="",
        qwen_api_key="",
        free_tier_enabled=False,
        critic_enabled=True,
        review_intensity="normal",
        database_path="./data/test_validation_fixes.db",
        api_secret="",
    )
    base.update(kwargs)
    return Settings(**base)


# ---------------------------------------------------------------------------
# MT-1
# ---------------------------------------------------------------------------


def test_low_intensity_substantive_question_invokes_primary():
    p = ProjectState(
        name="Logs",
        objective="Windows Event Log investigation",
        tech_stack=["Python", "FastAPI"],
    )
    msg = (
        "Project so far uses Python/FastAPI and rejected Elasticsearch. "
        "What database should we use and why?"
    )
    for intensity in ("low", "normal", "high"):
        d = decide_review_policy(
            message=msg, project=p, intensity=intensity, critic_available=False
        )
        assert d.action == ReviewAction.PRIMARY_ONLY, intensity
        assert d.detected_intent == MessageIntent.QUESTION


def test_low_intensity_greeting_still_conversation_only():
    p = ProjectState(name="P")
    d = decide_review_policy(message="hello", project=p, intensity="low")
    assert d.action == ReviewAction.CONVERSATION_ONLY


def test_trivial_ack_can_skip_model():
    p = ProjectState(name="P", objective="App")
    d = decide_review_policy(message="ok", project=p, intensity="low")
    assert d.action == ReviewAction.CONVERSATION_ONLY


@pytest.mark.asyncio
async def test_engine_low_intensity_calls_provider_for_question():
    repo = InMemoryProjectRepository()
    project = repo.create(
        ProjectState(name="Q", objective="Log MVP", intended_users=["analysts"])
    )
    calls: list[str] = []

    def primary(**_):
        calls.append("primary")
        return PrimaryAnalysis(
            reply="Given FastAPI, start with SQLite for the MVP.",
            intent="question",
            findings=[],
            state_patch=StatePatch(),
        )

    engine = GrillEngine(
        repo=repo,
        primary=MockProvider(primary_handler=primary, call_log=calls),
        critic=None,
        settings=_settings(review_intensity="low"),
        using_offline_primary=False,
    )
    res = await engine.handle_message(
        project.id,
        "What database should we use and why?",
        behavioural_mode=BehaviouralMode.PLAN,
    )
    assert "primary" in calls
    assert "SQLite" in res.message.content or "database" in res.message.content.lower()
    assert res.message.provenance.value != "none"


@pytest.mark.asyncio
async def test_provider_failure_falls_back_offline():
    repo = InMemoryProjectRepository()
    project = repo.create(ProjectState(name="Fail", objective="App"))

    class Boom(MockProvider):
        async def analyze_primary(self, **kwargs):
            self.call_log.append("primary")
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "down")

    engine = GrillEngine(
        repo=repo,
        primary=Boom(call_log=[]),
        critic=None,
        settings=_settings(review_intensity="low"),
        using_offline_primary=False,
    )
    res = await engine.handle_message(
        project.id,
        "What database should we use for the MVP?",
    )
    assert res.offline_review or res.provider_used == "offline" or res.message.content
    assert res.message.content  # still answered


# ---------------------------------------------------------------------------
# CX / CI-4 tech integrity
# ---------------------------------------------------------------------------


def test_postgres_to_mongodb_blocked_without_explicit_replace():
    p = ProjectState(
        name="X",
        objective="App",
        decisions=[Decision(title="Database", choice="PostgreSQL")],
        tech_stack=["PostgreSQL"],
    )
    p2, msgs = apply_state_patch(
        p, StatePatch(tech_stack=["MongoDB"]), mode=BehaviouralMode.PLAN
    )
    assert "PostgreSQL" in p2.tech_stack
    assert "MongoDB" not in p2.tech_stack
    assert msgs
    # MongoDB recorded as alternative
    db_sel = next(s for s in p2.technology_selections if s.selected == "PostgreSQL")
    assert "MongoDB" in db_sel.alternatives


def test_postgres_to_mongodb_explicit_replace_preserves_history():
    p = ProjectState(
        name="X",
        objective="App",
        tech_stack=["PostgreSQL"],
    )
    p, _ = apply_state_patch(p, StatePatch(tech_stack=["PostgreSQL"]))
    p2, msgs = apply_state_patch(
        p,
        StatePatch(tech_stack=["MongoDB"], replace_technology=True),
        mode=BehaviouralMode.PLAN,
    )
    assert "MongoDB" in p2.tech_stack
    assert "PostgreSQL" not in p2.tech_stack
    superseded = [s for s in p2.technology_selections if s.status == "superseded"]
    assert any(s.selected == "PostgreSQL" for s in superseded)


def test_mongodb_as_alternative_not_selection():
    sels, applied, cons, deferred = apply_technology_tokens(
        [],
        ["MongoDB or SQLite"],
    )
    assert applied == []
    assert any("Ambiguous" in d for d in deferred)
    assert any(s.status == "unverified" and "MongoDB" in s.alternatives for s in sels)


def test_react_plus_fastapi_coexist():
    p = ProjectState(name="X", objective="App")
    p2, msgs = apply_state_patch(
        p, StatePatch(tech_stack=["React", "FastAPI", "Python"])
    )
    assert set(p2.tech_stack) >= {"React", "FastAPI", "Python"}
    assert not any("conflict" in m.lower() for m in msgs)


def test_fastapi_vs_nodejs_conflict():
    p = ProjectState(name="X", objective="App", tech_stack=["Python", "FastAPI"])
    p, _ = apply_state_patch(p, StatePatch(tech_stack=["Python", "FastAPI"]))
    p2, msgs = apply_state_patch(p, StatePatch(tech_stack=["Node.js", "Express"]))
    assert "FastAPI" in p2.tech_stack
    assert "Node.js" not in p2.tech_stack
    assert "Express" not in p2.tech_stack
    assert msgs


def test_rejected_elasticsearch_stays_rejected():
    p = ProjectState(
        name="X",
        objective="Logs",
        rejected_approaches=[
            RejectedApproach(approach="Elasticsearch", reason="Infra complexity")
        ],
        tech_stack=["Python", "FastAPI", "SQLite"],
    )
    p, _ = apply_state_patch(
        p, StatePatch(tech_stack=["Python", "FastAPI", "SQLite"])
    )
    p2, msgs = apply_state_patch(p, StatePatch(tech_stack=["Elasticsearch"]))
    assert "Elasticsearch" not in p2.tech_stack
    assert any("elastic" in r.approach.lower() for r in p2.rejected_approaches)
    assert msgs


def test_invalid_llm_tech_tokens_not_persisted():
    assert parse_technology_token("MongoDB or SQLite").ambiguous
    p = ProjectState(name="X", objective="App")
    p2, msgs = apply_state_patch(p, StatePatch(tech_stack=["MongoDB or SQLite"]))
    assert "MongoDB or SQLite" not in p2.tech_stack
    assert p2.open_questions  # deferred clarification


def test_postgres_plus_redis_coexist():
    p = ProjectState(name="X", objective="App")
    p2, msgs = apply_state_patch(p, StatePatch(tech_stack=["PostgreSQL", "Redis"]))
    assert "PostgreSQL" in p2.tech_stack and "Redis" in p2.tech_stack
    assert not msgs


# ---------------------------------------------------------------------------
# CI-1 architecture notes
# ---------------------------------------------------------------------------


def test_architecture_notes_merge_compatible():
    p = ProjectState(
        name="X",
        objective="App",
        architecture_notes="Batch ingest then normalize.",
    )
    p2, msgs = apply_state_patch(
        p,
        StatePatch(architecture_notes="Expose investigation query API."),
    )
    assert "Batch ingest" in p2.architecture_notes
    assert "investigation query" in p2.architecture_notes.lower()
    assert not msgs
    assert p2.architecture_note_history


def test_architecture_notes_conflict_preserves_existing():
    p = ProjectState(
        name="X",
        objective="App",
        architecture_notes="Modular monolith with SQLite and synchronous request path.",
    )
    conflicting = (
        "Event-sourced microservices with Kafka streaming and polyglot persistence."
    )
    assert notes_conflict(p.architecture_notes, conflicting)
    p2, msgs = apply_state_patch(p, StatePatch(architecture_notes=conflicting))
    assert "Modular monolith" in p2.architecture_notes
    assert "Kafka" not in p2.architecture_notes
    assert msgs
    assert any(h.status == "proposed" for h in p2.architecture_note_history)


def test_architecture_notes_explicit_replace_keeps_history():
    p = ProjectState(
        name="X",
        objective="App",
        architecture_notes="Old architecture note.",
    )
    p2, msgs = apply_state_patch(
        p,
        StatePatch(
            architecture_notes="New confirmed architecture.",
            architecture_notes_mode="replace",
        ),
    )
    assert p2.architecture_notes == "New confirmed architecture."
    assert any(h.status == "superseded" for h in p2.architecture_note_history)
    assert not msgs


# ---------------------------------------------------------------------------
# CR-1 / CR-2 offline extraction
# ---------------------------------------------------------------------------


def test_offline_extract_stack_selection():
    ext = extract_explicit_tech_and_rejections("We are using Python and FastAPI.")
    assert ext.patch.tech_stack
    assert "Python" in ext.patch.tech_stack
    assert "FastAPI" in ext.patch.tech_stack


def test_offline_extract_database_and_rejection():
    ext = extract_explicit_tech_and_rejections(
        "Our database will be PostgreSQL. We rejected Elasticsearch because of infrastructure complexity."
    )
    assert ext.patch.tech_stack and "PostgreSQL" in ext.patch.tech_stack
    assert ext.patch.add_rejected_approaches
    assert any(
        "elastic" in r["approach"].lower() for r in ext.patch.add_rejected_approaches
    )


def test_offline_extract_ignores_brainstorm_questions():
    ext = extract_explicit_tech_and_rejections(
        "Should we maybe consider using MongoDB for this?"
    )
    assert not ext.patch.tech_stack
    assert not ext.patch.add_rejected_approaches


@pytest.mark.asyncio
async def test_offline_heuristic_retains_stack_and_rejection():
    repo = InMemoryProjectRepository()
    project = repo.create(ProjectState(name="Off", objective="Log platform"))
    engine = GrillEngine(
        repo=repo,
        primary=MockProvider(primary_handler=heuristic_primary),
        critic=None,
        settings=_settings(),
        using_offline_primary=True,
    )
    r1 = await engine.handle_message(
        project.id,
        "We are using Python and FastAPI.",
        behavioural_mode=BehaviouralMode.PLAN,
    )
    assert "Python" in r1.project.tech_stack
    assert "FastAPI" in r1.project.tech_stack

    r2 = await engine.handle_message(
        r1.project.id,
        "Reject Elasticsearch because of infrastructure complexity.",
        behavioural_mode=BehaviouralMode.PLAN,
    )
    assert any("elastic" in r.approach.lower() for r in r2.project.rejected_approaches)
    # Prior stack retained
    assert "Python" in r2.project.tech_stack
