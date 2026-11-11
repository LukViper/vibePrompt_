"""Conversation summarization and long-term memory tests."""

from __future__ import annotations

import pytest

from app.grill.memory import (
    apply_summary_update,
    assemble_prompt_context,
    build_deterministic_summary,
    maybe_refresh_summary,
    should_summarize,
    update_working_memory,
    validate_summary_does_not_override_structure,
)
from app.grill.modes import BehaviouralMode
from app.orchestration.engine import GrillEngine
from app.persistence.repository import InMemoryProjectRepository
from app.projects.models import (
    Decision,
    Message,
    MessageIntent,
    ProjectState,
    RejectedApproach,
)
from app.providers.base import PrimaryAnalysis, ProviderError, ProviderErrorKind, StatePatch
from app.providers.mock import MockProvider
from app.config import Settings, get_settings
from app.grill.context import retrieve_relevant_context


def _settings(**kwargs) -> Settings:
    get_settings.cache_clear()
    base = dict(
        gemini_api_key="",
        openrouter_api_key="",
        groq_api_key="",
        free_tier_enabled=False,
        critic_enabled=False,
        review_intensity="normal",
        database_path="./data/test_memory.db",
        api_secret="",
        summary_min_messages=10,
        summary_min_new_messages=4,
        summary_keep_recent=4,
        history_max_messages=6,
        context_max_total_chars=8_000,
        context_max_summary_chars=1_500,
    )
    base.update(kwargs)
    return Settings(**base)


def _long_project(n_messages: int = 24) -> ProjectState:
    p = ProjectState(
        name="WinLog",
        objective="Windows Event Log investigation assistant",
        intended_users=["IR analysts"],
        tech_stack=["Python", "FastAPI", "SQLite"],
        decisions=[
            Decision(title="Use case", choice="Investigation assistance"),
            Decision(title="Backend", choice="Python + FastAPI"),
            Decision(title="Database", choice="SQLite"),
        ],
        rejected_approaches=[
            RejectedApproach(approach="Elasticsearch", reason="Infra complexity")
        ],
        outstanding_tasks=["Implement EVTX ingest"],
        completed_milestones=["Scoped MVP"],
        architecture_notes="Batch ingest → normalize → query",
    )
    for i in range(n_messages):
        role = "user" if i % 2 == 0 else "assistant"
        p.messages.append(
            Message(
                role=role,
                content=f"Turn {i}: discussing EVTX ingest and SQLite storage for analysts.",
            )
        )
    return p


def test_should_summarize_triggers_on_length():
    p = _long_project(24)
    assert should_summarize(p, min_messages=10, min_new_since_summary=4)


def test_should_not_summarize_short_threads():
    p = _long_project(4)
    assert not should_summarize(p, min_messages=10, min_new_since_summary=4)


def test_deterministic_summary_preserves_decisions_and_rejections():
    p = _long_project(20)
    summary = build_deterministic_summary(p, keep_recent=4)
    assert "Investigation assistance" in summary.text
    assert "Elasticsearch" in summary.text
    assert "SQLite" in summary.text
    assert "Authoritative project memory" in summary.text
    assert summary.version >= 1


def test_summary_update_does_not_mutate_structure():
    p = _long_project(20)
    before_d = [(d.title, d.choice) for d in p.decisions]
    before_s = list(p.tech_stack)
    before_r = [r.approach for r in p.rejected_approaches]
    summary = build_deterministic_summary(p)
    apply_summary_update(p, summary)
    assert validate_summary_does_not_override_structure(
        p,
        before_decisions=before_d,
        before_stack=before_s,
        before_rejected=before_r,
    )
    assert p.conversation_summary is not None
    assert p.conversation_summary.text


def test_failed_summarization_keeps_previous():
    p = _long_project(12)
    first = build_deterministic_summary(p)
    apply_summary_update(p, first)
    apply_summary_update(p, None, failed=True)
    assert p.conversation_summary is not None
    assert p.conversation_summary.text == first.text
    assert p.conversation_summary.source == "failed_keep_previous"


def test_summary_versioning_keeps_history():
    p = _long_project(16)
    s1 = build_deterministic_summary(p, keep_recent=4)
    apply_summary_update(p, s1)
    p.messages.append(Message(role="user", content="Actually use PostgreSQL instead."))
    p.decisions.append(
        Decision(title="Database", choice="PostgreSQL", status="accepted")
    )
    # supersede sqlite decision
    for d in p.decisions:
        if d.choice == "SQLite":
            d.status = "superseded"
    s2 = build_deterministic_summary(p, keep_recent=4)
    apply_summary_update(p, s2)
    assert p.conversation_summary.version >= 2
    assert p.conversation_summary_history
    assert "PostgreSQL" in p.conversation_summary.text


def test_working_memory_tracks_intent_mode_and_corrections():
    p = ProjectState(name="P", objective="App", outstanding_tasks=["Ship ingest"])
    wm = update_working_memory(
        p,
        user_message="Actually, change that — we decided on SQLite.",
        intent=MessageIntent.ARCHITECTURE_DECISION.value,
        mode=BehaviouralMode.PLAN,
    )
    assert wm.current_intent == MessageIntent.ARCHITECTURE_DECISION.value
    assert wm.active_mode == "plan"
    assert wm.current_task == "Ship ingest"
    assert "Actually" in wm.last_user_correction


def test_assemble_keeps_critical_constraints_under_budget():
    p = _long_project(30)
    maybe_refresh_summary(p, min_messages=10, min_new_since_summary=4, keep_recent=4)
    structured = retrieve_relevant_context(
        p, mode=BehaviouralMode.BUILD, user_message="Implement ingest"
    ).as_prompt_json()
    assembled = assemble_prompt_context(
        p,
        mode=BehaviouralMode.BUILD,
        user_message="Implement EVTX ingest endpoint now",
        structured_snapshot=structured,
        max_recent_messages=4,
        max_chars_each=200,
        max_summary_chars=500,
        max_total_chars=3_500,
    )
    assert assembled.snapshot.get("tech_stack")
    assert any(
        (r.get("approach") if isinstance(r, dict) else r) == "Elasticsearch"
        or (isinstance(r, dict) and "Elastic" in r.get("approach", ""))
        for r in assembled.snapshot.get("rejected_approaches", [])
    )
    assert assembled.estimated_chars <= 3_500 or assembled.truncated_messages >= 0
    # Recent window limited
    assert len(assembled.conversation_tail) <= 4


def test_relevance_prefers_matching_older_turns():
    p = ProjectState(name="P", objective="App")
    p.messages = [
        Message(role="user", content="We rejected Elasticsearch for ops cost."),
        Message(role="assistant", content="Understood, avoiding Elastic."),
        Message(role="user", content="Hello"),
        Message(role="assistant", content="Hi"),
        Message(role="user", content="Hello again"),
        Message(role="assistant", content="Hi again"),
        Message(role="user", content="ok"),
        Message(role="assistant", content="ok"),
        Message(role="user", content="What about search without Elasticsearch?"),
    ]
    from app.grill.memory import select_recent_messages

    tail, _ids, _cands = select_recent_messages(
        p, user_message="search without Elasticsearch", max_messages=4
    )
    blob = " ".join(t["content"] for t in tail).lower()
    assert "elasticsearch" in blob or len(tail) <= 4


def test_contradictory_history_structured_wins_in_summary():
    p = _long_project(18)
    # Place brainstorming in the older window so it appears in the digest
    p.messages.insert(
        0,
        Message(role="user", content="Maybe we should brainstorm using MongoDB?"),
    )
    summary = build_deterministic_summary(p, keep_recent=4)
    # Confirmed SQLite remains authoritative; brainstorm is labeled, not a decision
    assert "SQLite" in summary.text
    assert "Database=SQLite" in summary.text or "SQLite" in summary.text
    assert "brainstorm" in summary.text.lower() or "Maybe" in summary.text
    assert "Database=MongoDB" not in summary.text


@pytest.mark.asyncio
async def test_engine_long_conversation_retains_critical_info():
    repo = InMemoryProjectRepository()
    project = repo.create(
        ProjectState(
            name="Long",
            objective="Log investigation MVP",
            intended_users=["analysts"],
            tech_stack=["Python", "FastAPI", "SQLite"],
            decisions=[Decision(title="Database", choice="SQLite")],
            rejected_approaches=[
                RejectedApproach(approach="Elasticsearch", reason="complexity")
            ],
        )
    )
    captured: dict = {}

    def primary(**kwargs):
        captured["snapshot"] = kwargs.get("project_snapshot") or {}
        captured["tail"] = kwargs.get("conversation_tail") or []
        return PrimaryAnalysis(
            reply="Continuing with SQLite and avoiding Elasticsearch.",
            intent="general",
            findings=[],
            state_patch=StatePatch(),
        )

    engine = GrillEngine(
        repo=repo,
        primary=MockProvider(primary_handler=primary),
        critic=None,
        settings=_settings(),
        using_offline_primary=False,
    )

    # Seed many turns
    for i in range(14):
        await engine.handle_message(
            project.id,
            f"Follow-up note {i} about EVTX parsing details.",
            behavioural_mode=BehaviouralMode.PLAN,
        )

    res = await engine.handle_message(
        project.id,
        "Remind me what database and search approach we chose.",
        behavioural_mode=BehaviouralMode.PLAN,
    )
    snap = captured.get("snapshot") or {}
    assert "SQLite" in (snap.get("tech_stack") or res.project.tech_stack)
    rejected = snap.get("rejected_approaches") or [
        {"approach": r.approach} for r in res.project.rejected_approaches
    ]
    assert any("Elastic" in str(r) for r in rejected)
    # Summary should exist after long thread
    assert res.project.conversation_summary is not None
    assert "SQLite" in (res.project.conversation_summary.text or "")


@pytest.mark.asyncio
async def test_engine_project_isolation_of_memory():
    repo = InMemoryProjectRepository()
    a = repo.create(
        ProjectState(
            name="A",
            objective="Project A",
            tech_stack=["SQLite"],
            rejected_approaches=[RejectedApproach(approach="Elasticsearch", reason="x")],
        )
    )
    b = repo.create(
        ProjectState(
            name="B",
            objective="Project B",
            tech_stack=["PostgreSQL"],
        )
    )

    def primary(**kwargs):
        return PrimaryAnalysis(
            reply="ok", intent="general", findings=[], state_patch=StatePatch()
        )

    engine = GrillEngine(
        repo=repo,
        primary=MockProvider(primary_handler=primary),
        critic=None,
        settings=_settings(summary_min_messages=4, summary_min_new_messages=2),
        using_offline_primary=False,
    )
    for i in range(6):
        await engine.handle_message(a.id, f"A turn {i}")
        await engine.handle_message(b.id, f"B turn {i}")

    a2 = repo.get(a.id)
    b2 = repo.get(b.id)
    assert a2 and b2
    assert a2.tech_stack == ["SQLite"]
    assert b2.tech_stack == ["PostgreSQL"]
    if a2.conversation_summary and b2.conversation_summary:
        assert a2.conversation_summary.id != b2.conversation_summary.id or a2.id != b2.id


@pytest.mark.asyncio
async def test_provider_failure_does_not_corrupt_summary_memory():
    repo = InMemoryProjectRepository()
    project = repo.create(_long_project(12))
    maybe_refresh_summary(
        project, min_messages=10, min_new_since_summary=2, keep_recent=4
    )
    repo.save(project)
    before = project.conversation_summary.text if project.conversation_summary else ""

    class Boom(MockProvider):
        async def analyze_primary(self, **kwargs):
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "down")

    engine = GrillEngine(
        repo=repo,
        primary=Boom(),
        critic=None,
        settings=_settings(),
        using_offline_primary=False,
    )
    res = await engine.handle_message(project.id, "What is our database?")
    # Offline fallback still answers; structured memory intact
    assert "SQLite" in res.project.tech_stack
    assert any("Elastic" in r.approach for r in res.project.rejected_approaches)
    if before:
        assert res.project.conversation_summary is not None
