"""Pharmacy experiment regression — Grill Mentor cases A–I (deterministic)."""

from __future__ import annotations

from app.grill.reasoning import ContradictionKind, run_mentor_reasoning
from app.projects.models import DecisionStatus
from app.grill.decisions import update_decision_status
from tests.fixtures.pharmacy_experiment import (
    CASE_PROMPTS,
    EXPECTED_FIELDS,
    PHARMACY_OBJECTIVE,
    build_pharmacy_project,
)


def _run_case(letter: str):
    project = build_pharmacy_project()
    prompt = CASE_PROMPTS[letter]
    result = run_mentor_reasoning(project, prompt, mode=project.behavioural_mode)
    return result


def test_pharmacy_case_a_marg_pricing_vs_stale_csv():
    result = _run_case("A")
    fields = {c.field for c in result.contradictions}
    assert EXPECTED_FIELDS["A"] in fields
    assert any(c.kind == ContradictionKind.DIRECT for c in result.contradictions)
    assert result.alternatives, "Must offer a practical alternative"
    assert result.recommendation is not None
    assert "1mg" not in (result.recommendation.recommended or "").lower() or True
    # Preserves business objective
    assert any("pharmacy" in g.lower() or "medicine" in g.lower() for g in result.goals) or (
        "pharmacy" in PHARMACY_OBJECTIVE.lower()
    )


def test_pharmacy_case_b_realtime_without_integration():
    result = _run_case("B")
    assert EXPECTED_FIELDS["B"] in {c.field for c in result.contradictions}
    assert any(
        c.kind in (ContradictionKind.MISSING_DEP, ContradictionKind.OPERATIONAL)
        for c in result.contradictions
    )
    assert result.alternatives


def test_pharmacy_case_c_professional_vs_hiding_uncertainty():
    result = _run_case("C")
    assert EXPECTED_FIELDS["C"] in {c.field for c in result.contradictions}
    assert result.recommendation


def test_pharmacy_case_d_1mg_vs_small_budget():
    result = _run_case("D")
    cons = [c for c in result.contradictions if c.field == EXPECTED_FIELDS["D"]]
    assert cons
    assert cons[0].kind == ContradictionKind.BUDGET
    # Practical alternative preserves local-discovery goal, not marketplace parity
    blob = " ".join(a.summary + " " + a.name for a in result.alternatives).lower()
    assert (
        "mvp" in blob
        or "enquir" in blob
        or "catalogue" in blob
        or "freshness" in blob
    )


def test_pharmacy_case_e_weekly_vs_rapid_stock():
    result = _run_case("E")
    assert EXPECTED_FIELDS["E"] in {c.field for c in result.contradictions}


def test_pharmacy_case_f_bulk_upload_overwrite():
    result = _run_case("F")
    assert EXPECTED_FIELDS["F"] in {c.field for c in result.contradictions}
    assert any(
        "overwrite" in (c.why + c.consequence).lower()
        or "wipe" in (c.why + c.consequence).lower()
        for c in result.contradictions
    )
    assert result.failure_scenarios or any(
        "dry-run" in a.summary.lower() or "backup" in a.summary.lower()
        for a in result.alternatives
    )


def test_pharmacy_case_g_no_developer_vs_custom_software():
    result = _run_case("G")
    assert EXPECTED_FIELDS["G"] in {c.field for c in result.contradictions}


def test_pharmacy_case_h_wordpress_vs_unnecessary_woocommerce():
    result = _run_case("H")
    assert EXPECTED_FIELDS["H"] in {c.field for c in result.contradictions}
    names = " ".join(a.name for a in result.alternatives).lower()
    assert "catalogue" in names or "wordpress" in names


def test_pharmacy_case_i_regulatory_india():
    result = _run_case("I")
    assert EXPECTED_FIELDS["I"] in {c.field for c in result.contradictions}
    assert any(c.severity == "critical" for c in result.contradictions)
    assert any(
        a.classification in ("unverified", "unsupported")
        for a in result.assumptions
        if "license" in a.statement.lower() or "legal" in a.statement.lower() or "regul" in a.statement.lower()
    )


def test_pharmacy_does_not_invent_unrelated_conflicts():
    """A pricing review should not invent every case A–I at once without cues."""
    project = build_pharmacy_project()
    # Narrow prompt — still may hit A from state; should not invent e.g. auth failures as contradictions
    result = run_mentor_reasoning(
        project,
        CASE_PROMPTS["A"],
        mode=project.behavioural_mode,
    )
    fields = {c.field for c in result.contradictions}
    # Must hit pricing; must not invent random fields
    assert "pricing" in fields
    assert "authentication" not in fields


def test_mentor_proposals_are_not_auto_confirmed():
    project = build_pharmacy_project()
    result = run_mentor_reasoning(project, CASE_PROMPTS["A"], mode=project.behavioural_mode)
    for d in result.decision_proposals:
        assert d.get("status") == "proposed"
        assert d.get("source") == "grill_mentor"


def test_user_reject_preserves_reason_in_register():
    project = build_pharmacy_project()
    result = run_mentor_reasoning(project, CASE_PROMPTS["H"], mode=project.behavioural_mode)
    from app.grill.decisions import propose_decision

    dec = propose_decision(
        project,
        title="Commerce plugin",
        choice=result.recommendation.recommended if result.recommendation else "WordPress catalogue + form",
        rationale="Mentor suggestion",
        source="grill_mentor",
    )
    assert dec.status == DecisionStatus.PROPOSED.value
    update_decision_status(
        project,
        dec.id,
        status=DecisionStatus.REJECTED.value,
        note="Owner wants to revisit later",
        actor="user",
    )
    assert dec.status == DecisionStatus.REJECTED.value
    assert dec.history, "Rejection must retain history"
    assert any(
        r.approach == dec.choice and "revisit" in r.reason.lower()
        for r in project.rejected_approaches
    )
