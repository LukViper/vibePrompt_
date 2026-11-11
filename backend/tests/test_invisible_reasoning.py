"""Regression: critical reasoning is invisible — answers the latest ask without stale reports."""

from __future__ import annotations

from app.grill.decisions import update_decision_status
from app.grill.modes import BehaviouralMode
from app.grill.reasoning import (
    format_mentor_reply,
    merge_reasoning_into_analysis,
    run_mentor_reasoning,
)
from app.projects.models import (
    Decision,
    DecisionStatus,
    Finding,
    FindingStatus,
    Message,
    ProjectState,
    Requirement,
    Severity,
)
from app.projects.state_apply import apply_state_patch
from app.providers.base import PrimaryAnalysis, StatePatch


def _tech_heavy_project() -> ProjectState:
    return ProjectState(
        name="LogLens",
        objective="Windows Event Log investigation assistant for SOC analysts",
        tech_stack=["Python", "SQLite", "FastAPI"],
        decisions=[
            Decision(
                title="Database",
                choice="SQLite",
                rationale="Local MVP",
                status=DecisionStatus.CONFIRMED.value,
                source="user",
            ),
            Decision(
                title="API framework",
                choice="FastAPI",
                status=DecisionStatus.CONFIRMED.value,
                source="user",
            ),
        ],
        functional_requirements=[
            Requirement(text="Ingest Windows EVTX files"),
            Requirement(text="Query logs by Event ID"),
        ],
        messages=[
            Message(role="user", content="Let's use FastAPI and SQLite for the MVP."),
            Message(
                role="assistant",
                content="Sounds good — FastAPI + SQLite fits a local investigation tool.",
            ),
            Message(
                role="user",
                content="Also add pagination and EVTX parsing with python-evtx.",
            ),
            Message(
                role="assistant",
                content="We can add cursor pagination and python-evtx for ingest.",
            ),
        ],
        behavioural_mode=BehaviouralMode.PLAN,
    )


def test_1_business_question_after_technical_discussion():
    """Latest business ask is answered; do not recycle a tech-stack review."""
    p = _tech_heavy_project()
    ask = (
        "Quick business question: who should we charge first — internal SOC teams "
        "or sell to MSSPs? Ignore the stack for a moment."
    )
    r = run_mentor_reasoning(p, ask, mode=BehaviouralMode.EXPLORE)
    reply = format_mentor_reply(
        r,
        base_reply=(
            "For an early MVP, start with internal SOC teams — shorter sales cycle "
            "and clearer feedback — then consider MSSPs once the workflow is proven."
        ),
        mode=BehaviouralMode.EXPLORE,
    )
    low = reply.lower()
    assert "soc" in low or "mssps" in low or "internal" in low
    assert "**verdict.**" not in low
    assert "mode:" not in low
    # Should not dominate with SQLite/FastAPI critique
    assert low.count("sqlite") <= 1


def test_2_contradiction_between_two_requirements():
    p = ProjectState(
        name="Local Pharmacy Shop",
        objective="Local pharmacy catalogue for nearby customers in India",
        functional_requirements=[
            Requirement(text="Show exact Marg prices from weekly CSV"),
            Requirement(text="Guarantee real-time stock accuracy with no integration"),
        ],
        constraints=[],
        architecture_notes=(
            "Marg billing software, weekly CSV inventory uploads, real-time sync "
            "expectations, no known integration, pharmacy catalogue"
        ),
        behavioural_mode=BehaviouralMode.PLAN,
    )
    ask = (
        "We need exact Marg pricing from the weekly CSV and also real-time "
        "synchronization with no known integration. Is that consistent?"
    )
    r = run_mentor_reasoning(p, ask, mode=BehaviouralMode.PLAN)
    assert r.contradictions, "Must detect the requirement conflict"
    reply = format_mentor_reply(r, base_reply="Let me check consistency.", mode=BehaviouralMode.PLAN)
    assert "tension" in reply.lower() or "practical" in reply.lower() or r.recommendation
    assert "**Verdict.**" not in reply


def test_3_user_changing_confirmed_decision():
    p = _tech_heavy_project()
    ask = (
        "I changed my mind — replace SQLite with PostgreSQL for the database. "
        "Please update the plan."
    )
    # Simulate primary proposing replace
    patch = StatePatch(
        add_decisions=[
            {
                "title": "Database",
                "choice": "PostgreSQL",
                "status": "confirmed",
                "replace": True,
                "rationale": "User explicitly replaced SQLite",
                "source": "user",
            }
        ]
    )
    p2, msgs = apply_state_patch(p, patch, mode=BehaviouralMode.PLAN, allow_contradictions=True)
    active = [
        d
        for d in p2.decisions
        if d.title.lower() == "database"
        and d.status not in (DecisionStatus.SUPERSEDED.value, DecisionStatus.REJECTED.value)
    ]
    assert any(d.choice == "PostgreSQL" for d in active)
    assert any(d.status == DecisionStatus.SUPERSEDED.value and d.choice == "SQLite" for d in p2.decisions)
    # Reasoning should not fight the explicit replace as a stale critique
    r = run_mentor_reasoning(p2, ask, mode=BehaviouralMode.PLAN)
    reply = format_mentor_reply(
        r,
        base_reply="Understood — PostgreSQL is now the database choice.",
        mode=BehaviouralMode.PLAN,
    )
    assert "postgresql" in reply.lower() or "understood" in reply.lower()


def test_4_request_with_no_contradictions():
    p = ProjectState(
        name="Notes",
        objective="Personal markdown notes with local SQLite",
        decisions=[
            Decision(title="Database", choice="SQLite", status=DecisionStatus.CONFIRMED.value)
        ],
        behavioural_mode=BehaviouralMode.EXPLORE,
    )
    ask = "We'll stick with SQLite and a tiny Flask API for the MVP. Sound good?"
    r = run_mentor_reasoning(p, ask, mode=BehaviouralMode.EXPLORE)
    assert r.acknowledge_reasonable or not r.contradictions
    reply = format_mentor_reply(
        r,
        base_reply="Yes — SQLite plus a small Flask API is a solid MVP.",
        mode=BehaviouralMode.EXPLORE,
    )
    assert "**Verdict.**" not in reply
    assert "tension to watch" not in reply.lower()


def test_5_unrelated_new_request():
    p = _tech_heavy_project()
    ask = (
        "Completely unrelated: can you suggest a simple pasta recipe for dinner tonight "
        "with tomato and garlic?"
    )
    r = run_mentor_reasoning(p, ask, mode=BehaviouralMode.EXPLORE)
    assert not r.contradictions, "Must not revive project tensions for an unrelated ask"
    reply = format_mentor_reply(
        r,
        base_reply=(
            "Sure — sauté garlic in olive oil, add tomatoes, simmer 15 minutes, "
            "toss with pasta and salt."
        ),
        mode=BehaviouralMode.EXPLORE,
    )
    low = reply.lower()
    assert "pasta" in low or "garlic" in low or "tomato" in low
    assert "sqlite" not in low
    assert "fastapi" not in low


def test_6_resolved_issue_not_raised_again():
    p = _tech_heavy_project()
    p.findings.append(
        Finding(
            title="SQLite vs scale",
            challenged_claim="SQLite cannot handle concurrent SOC analysts",
            reasoning="Discussed and accepted for MVP",
            severity=Severity.HIGH,
            status=FindingStatus.RESOLVED,
            resolution_note="Accepted for single-analyst MVP",
        )
    )
    ask = "What should we work on next for EVTX ingest?"
    r = run_mentor_reasoning(p, ask, mode=BehaviouralMode.BUILD)
    reply = format_mentor_reply(
        r,
        base_reply="Next: implement EVTX upload and parse a sample file end-to-end.",
        mode=BehaviouralMode.BUILD,
    )
    low = reply.lower()
    assert "evtx" in low or "ingest" in low or "next" in low
    # Stale resolved concurrency critique should not dominate
    assert "concurrent soc" not in low
    for c in r.contradictions:
        assert "concurrent" not in c.why.lower()


def test_merge_keeps_one_coherent_answer_without_orchestration_jargon():
    p = _tech_heavy_project()
    reply, findings, patch, mentor = merge_reasoning_into_analysis(
        "Pagination on Event ID queries is the right next slice.",
        p,
        "How should we paginate Event ID search results?",
        mode=BehaviouralMode.BUILD,
    )
    assert "Mentor reasoning" not in reply
    assert "MODE:" not in reply
    assert "**Verdict.**" not in reply
    assert "paginate" in reply.lower() or "event id" in reply.lower()


def test_persona_instructions_do_not_instruct_exposing_mode_names():
    from app.grill.persona import instructions_for_mode

    for mode in (
        BehaviouralMode.EXPLORE,
        BehaviouralMode.PLAN,
        BehaviouralMode.BUILD,
        BehaviouralMode.REVIEW,
        BehaviouralMode.DEBUG,
    ):
        text = instructions_for_mode(mode)
        assert "never tell the user" in text.lower() or "internal" in text.lower()
