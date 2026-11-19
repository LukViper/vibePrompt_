"""REVIEW fail-closed gate — unseeded bad go-live brief must block."""

from __future__ import annotations

import pytest

from app.compilation.readiness import assess_readiness
from app.grill.lifecycle import merge_candidates_into_project, update_finding_status
from app.grill.modes import BehaviouralMode
from app.grill.reasoning import ContradictionKind, run_mentor_reasoning
from app.grill.tech import TechnologySelection
from app.projects.models import (
    Decision,
    FindingStatus,
    ProjectState,
    RejectedApproach,
    ReviewProvenance,
)


def _bad_golive_project() -> ProjectState:
    """Zero pre-seeded assumption rows; contradictions live in brief + state."""
    return ProjectState(
        name="VibePrompt",
        objective="Ship Invisible Grill single-node beta",
        assumptions=[],
        technology_selections=[
            TechnologySelection(
                category="database", selected="SQLite", status="accepted"
            ),
        ],
        tech_stack=["SQLite", "FastAPI", "React"],
        decisions=[
            Decision(
                title="DB",
                choice="SQLite for single-node beta",
                status="confirmed",
            ),
        ],
        rejected_approaches=[
            RejectedApproach(
                approach="Hosting FastAPI on Vercel",
                reason="No persistent volume / long LLM calls",
            ),
        ],
        behavioural_mode=BehaviouralMode.REVIEW,
    )


BAD_BRIEF = (
    "Approve go-live as public multi-user SaaS. "
    "Production setup is SQLite + Postgres together. "
    "Host the API on Vercel serverless for long LLM reviews. "
    "All eight Books-to-Skill titles are live and active."
)


def test_review_unseeded_bad_golive_returns_three_blocking_findings():
    project = _bad_golive_project()
    assert project.assumptions == []

    result = run_mentor_reasoning(
        project, BAD_BRIEF, mode=BehaviouralMode.REVIEW
    )
    assert result.acknowledge_reasonable is False
    assert "review_blocking_gate" in result.stages_run

    blocking = [
        c
        for c in result.contradictions
        if c.kind == ContradictionKind.BLOCKING
        and c.severity == "high"
    ]
    assert len(blocking) >= 3

    why_blob = " ".join(c.why.lower() for c in blocking)
    assert "persist" in why_blob or "sqlite" in why_blob or "database" in why_blob
    assert "vercel" in why_blob or "hosting" in why_blob or "rejected" in why_blob
    assert "book" in why_blob or "manifest" in why_blob or "artifact" in why_blob

    findings = result.to_findings()
    high = [f for f in findings if f.severity == "high"]
    assert len(high) >= 3
    assert all(f.kind == ContradictionKind.BLOCKING for f in high[:3])

    project.findings = merge_candidates_into_project(
        [], findings, provenance=ReviewProvenance.PRIMARY_ONLY
    )
    readiness = assess_readiness(project)
    assert readiness.ready is False
    assert readiness.status == "not_ready"
    assert any("Blocking Contradiction" in b for b in readiness.blockers)


def test_blocking_finding_rejects_insistence_without_evidence():
    project = _bad_golive_project()
    result = run_mentor_reasoning(project, BAD_BRIEF, mode=BehaviouralMode.REVIEW)
    findings = merge_candidates_into_project(
        [], result.to_findings(), provenance=ReviewProvenance.PRIMARY_ONLY
    )
    blocking = next(f for f in findings if f.is_blocking_contradiction)

    with pytest.raises(ValueError, match="insistence"):
        update_finding_status(blocking, FindingStatus.REJECTED, note="just ship it")

    update_finding_status(
        blocking,
        FindingStatus.RESOLVED,
        note="Updated state: removed Postgres; manifest claim corrected to 6 active titles.",
    )
    assert blocking.status == FindingStatus.RESOLVED


def test_negated_exclusions_do_not_trigger_blocking_contradictions():
    """Explicit rejections in prose must not false-positive the REVIEW gate."""
    from app.grill.review_gate import detect_review_blocking_contradictions

    project = _bad_golive_project()
    brief = (
        "We are locking SQLite only—no Postgres and no Vercel backend. "
        "Sticking strictly to the single-node beta."
    )
    findings = detect_review_blocking_contradictions(project, brief)
    assert findings == [], [f.why for f in findings]

    result = run_mentor_reasoning(project, brief, mode=BehaviouralMode.REVIEW)
    blocking = [c for c in result.contradictions if c.kind == ContradictionKind.BLOCKING]
    assert blocking == []


def test_affirmative_dual_stack_still_triggers_blocking_contradictions():
    from app.grill.review_gate import detect_review_blocking_contradictions

    project = _bad_golive_project()
    brief = "We will run SQLite locally and Postgres in prod on Vercel."
    findings = detect_review_blocking_contradictions(project, brief)
    assert len(findings) >= 1
    why = " ".join(f.why.lower() for f in findings)
    assert "persist" in why or "database" in why or "sqlite" in why or "vercel" in why or "rejected" in why
    assert all(f.kind == ContradictionKind.BLOCKING for f in findings)
    assert all(f.severity == "high" for f in findings)
