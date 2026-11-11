"""Unit tests for mentor reasoning pipeline and decision register."""

from __future__ import annotations

from app.grill.decisions import apply_decision_dict, update_decision_status
from app.grill.reasoning import format_mentor_reply, run_mentor_reasoning
from app.grill.modes import BehaviouralMode
from app.projects.models import Decision, DecisionStatus, ProjectState
from app.providers.base import StatePatch
from app.projects.state_apply import apply_state_patch


def test_stages_run_complete():
    p = ProjectState(name="X", objective="Ship an MVP notes app")
    r = run_mentor_reasoning(p, "Does SQLite work for this?", mode=BehaviouralMode.PLAN)
    assert "intent_and_goals" in r.stages_run
    assert "decision_tracking" in r.stages_run
    assert len(r.stages_run) >= 8


def test_acknowledge_reasonable_idea():
    p = ProjectState(
        name="Notes",
        objective="Local markdown notes with SQLite",
        decisions=[Decision(title="Database", choice="SQLite", status="confirmed")],
    )
    r = run_mentor_reasoning(
        p,
        "We'll stick with SQLite and a small Flask API for the MVP.",
        mode=BehaviouralMode.EXPLORE,
    )
    assert r.acknowledge_reasonable or not r.contradictions
    reply = format_mentor_reply(r)
    assert "reasonable" in reply.lower() or not r.contradictions


def test_confirmed_decision_not_silently_overwritten():
    p = ProjectState(
        name="App",
        objective="MVP",
        decisions=[Decision(title="Database", choice="SQLite", status="confirmed")],
    )
    patch = StatePatch(
        add_decisions=[
            {
                "title": "Database",
                "choice": "MongoDB cluster",
                "status": "proposed",
                "source": "grill_mentor",
            }
        ]
    )
    p2, msgs = apply_state_patch(p, patch, mode=BehaviouralMode.PLAN)
    # Confirmed SQLite retained
    active = [d for d in p2.decisions if d.status not in ("superseded", "rejected")]
    assert any(d.choice == "SQLite" for d in active)
    # Mentor proposal may appear under proposed change title or be blocked with message
    assert msgs or any("proposed" in d.status for d in p2.decisions)


def test_accept_recommendation_updates_register_with_history():
    p = ProjectState(name="App", objective="MVP")
    _dec, err = apply_decision_dict(
        p,
        {
            "title": "Hosting",
            "choice": "Single VPS",
            "status": "proposed",
            "source": "grill_mentor",
        },
    )
    assert err is None
    dec = p.decisions[0]
    assert dec.status == DecisionStatus.PROPOSED.value
    update_decision_status(
        p, dec.id, status=DecisionStatus.CONFIRMED.value, note="User accepted", actor="user"
    )
    assert dec.status == DecisionStatus.CONFIRMED.value
    assert dec.history
    assert "accepted" in dec.history[-1].note.lower() or "confirmed" in dec.history[-1].status


def test_response_is_conversational_not_a_report():
    from tests.fixtures.pharmacy_experiment import CASE_PROMPTS, build_pharmacy_project

    p = build_pharmacy_project()
    r = run_mentor_reasoning(p, CASE_PROMPTS["A"], mode=BehaviouralMode.REVIEW)
    text = format_mentor_reply(r, mode=BehaviouralMode.REVIEW, expose_structure=False)
    assert "**Verdict.**" not in text
    assert "MODE:" not in text
    assert r.verdict or r.recommendation
    # Explicit structure still available for tooling
    structured = format_mentor_reply(r, expose_structure=True)
    assert "Verdict" in structured or r.verdict
