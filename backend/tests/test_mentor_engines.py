"""Tests for Grill persona, context, orchestration, and agent-prompt engines."""

from __future__ import annotations

import pytest

from app.compilation.agent_prompt import compile_agent_prompt
from app.grill.context import (
    apply_manual_context_update,
    detect_contradictions,
    filter_brainstorm_patch,
    retrieve_relevant_context,
)
from app.grill.modes import BehaviouralMode, detect_behavioural_mode, resolve_project_mode
from app.grill.persona import SHARED_IDENTITY, instructions_for_mode, is_adversarial_mode
from app.grill.validate import validate_analysis_for_mode
from app.projects.models import Decision, ProjectState, RejectedApproach, Requirement
from app.providers.base import PrimaryAnalysis, StatePatch
from app.providers.prompts import build_primary_system
from app.projects.state_apply import apply_state_patch
from tests.conftest import build_engine


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------


def test_persona_identity_is_collaborator_with_invisible_critique():
    low = SHARED_IDENTITY.lower()
    assert "vibeprompt" in low
    assert "never invent" in low
    assert "mvp" in low
    assert "quietly" in low or "always on" in low
    assert "/grill" not in low


def test_persona_challenges_only_material_risks_in_review():
    review = instructions_for_mode(BehaviouralMode.REVIEW)
    assert "do not manufacture" in review.lower()
    assert "material" in review.lower()
    assert is_adversarial_mode(BehaviouralMode.REVIEW)
    assert not is_adversarial_mode(BehaviouralMode.EXPLORE)


def test_persona_explore_stays_conversational():
    explore = instructions_for_mode(BehaviouralMode.EXPLORE)
    assert "incomplete" in explore.lower()
    assert "at most one" in explore.lower()
    assert "MODE: EXPLORE" in explore


def test_prompts_include_new_modes():
    for mode in (
        BehaviouralMode.EXPLORE,
        BehaviouralMode.PLAN,
        BehaviouralMode.BUILD,
        BehaviouralMode.REVIEW,
        BehaviouralMode.DEBUG,
    ):
        text = build_primary_system(mode)
        assert mode.value.upper() in text or mode.name in text


def test_legacy_prompt_labels_still_present():
    chat = build_primary_system(BehaviouralMode.CONVERSATIONAL)
    brain = build_primary_system(BehaviouralMode.BRAINSTORMING)
    grill = build_primary_system(BehaviouralMode.GRILL_REVIEW)
    assert "CONVERSATIONAL" in chat
    assert "BRAINSTORMING" in brain
    assert "GRILL_REVIEW" in grill
    assert "review" in grill.lower() or "evidence" in grill.lower()
    assert "do not refuse" in chat.lower() or "incomplete" in chat.lower() or "quietly" in chat.lower()


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


def test_context_persists_requirements_across_patches():
    project = ProjectState(name="Logs", objective="")
    project, _ = apply_state_patch(
        project,
        StatePatch(
            objective="Cybersecurity log analysis platform",
            intended_users=["SOC analysts"],
            add_functional_requirements=["Ingest Windows event logs"],
            add_decisions=[
                {
                    "title": "Initial log source",
                    "choice": "Windows Event Logs",
                    "rationale": "User confirmed",
                }
            ],
        ),
        mode=BehaviouralMode.PLAN,
    )
    project, _ = apply_state_patch(
        project,
        StatePatch(
            add_preferences=["Investigation assistance"],
            add_scope_out=["Real-time detection engine"],
        ),
        mode=BehaviouralMode.PLAN,
    )
    assert project.objective.startswith("Cybersecurity")
    assert "SOC analysts" in project.intended_users
    assert any("Windows" in r.text for r in project.functional_requirements)
    assert project.decisions[0].choice == "Windows Event Logs"
    assert "Investigation assistance" in project.preferences


def test_rejected_approaches_not_reapplied():
    project = ProjectState(
        name="Logs",
        objective="Investigate Windows logs",
        rejected_approaches=[
            RejectedApproach(
                approach="Kafka + Kubernetes streaming",
                reason="Too heavy for MVP",
            )
        ],
        decisions=[
            Decision(title="Architecture", choice="Batch ingest + query UI")
        ],
    )
    patch = StatePatch(tech_stack=["Kubernetes", "Kafka"])
    contradictions = detect_contradictions(project, patch)
    assert contradictions
    project, msgs = apply_state_patch(project, patch, mode=BehaviouralMode.PLAN)
    assert msgs
    assert "Kubernetes" not in project.tech_stack


def test_contradiction_on_conflicting_decision():
    project = ProjectState(
        name="App",
        objective="MVP",
        decisions=[Decision(title="Database", choice="SQLite")],
    )
    patch = StatePatch(
        add_decisions=[{"title": "Database", "choice": "MongoDB sharding cluster"}]
    )
    assert detect_contradictions(project, patch)
    project, msgs = apply_state_patch(project, patch)
    assert msgs
    assert project.decisions[0].choice == "SQLite"


def test_explore_demotes_speculative_decisions():
    patch = StatePatch(
        add_decisions=[
            {"title": "Maybe use Redis", "choice": "Redis everywhere"},
            {"title": "Database", "choice": "SQLite", "rationale": "Confirmed"},
        ]
    )
    filtered = filter_brainstorm_patch(patch, BehaviouralMode.EXPLORE)
    assert filtered.add_decisions and filtered.add_decisions[0]["choice"] == "SQLite"
    assert filtered.add_assumptions
    assert "Provisional" in filtered.add_assumptions[0]


def test_context_retrieval_is_mode_relevant():
    project = ProjectState(
        name="Logs",
        objective="Investigate Windows logs",
        problem_statement="Analysts drown in raw event noise",
        intended_users=["IR analysts"],
        tech_stack=["Python", "SQLite"],
        architecture_notes="Batch normalize then query",
        rejected_approaches=[
            RejectedApproach(approach="Real-time SIEM clone", reason="Out of MVP")
        ],
        outstanding_tasks=["Build ingest pipeline"],
        known_risks=["Parser drift across Windows versions"],
        functional_requirements=[
            Requirement(text="Ingest EVTX", acceptance_criteria=["Can load a sample file"])
        ],
    )
    explore = retrieve_relevant_context(project, mode=BehaviouralMode.EXPLORE)
    assert "open_questions" in explore.snapshot
    assert "outstanding_tasks" not in explore.snapshot

    build = retrieve_relevant_context(project, mode=BehaviouralMode.BUILD)
    assert "outstanding_tasks" in build.snapshot
    assert build.snapshot["tech_stack"] == ["Python", "SQLite"]
    assert build.snapshot["rejected_approaches"]

    debug = retrieve_relevant_context(
        project,
        mode=BehaviouralMode.DEBUG,
        user_message="TypeError: NoneType in parser\nTraceback...",
    )
    assert debug.snapshot.get("recent_error_cues")


def test_manual_context_update_and_inspect():
    project = ProjectState(name="X", objective="Y")
    project, applied = apply_manual_context_update(
        project,
        {
            "problem_statement": "Painful log triage",
            "tech_stack": ["Python"],
            "rejected_approaches": [{"approach": "ELK full stack", "reason": "Ops cost"}],
        },
    )
    assert "problem_statement" in applied
    assert project.problem_statement == "Painful log triage"
    assert project.rejected_approaches[0].approach == "ELK full stack"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def test_mode_detection_five_modes():
    assert detect_behavioural_mode("who is the user and what's the real problem") == BehaviouralMode.EXPLORE
    assert detect_behavioural_mode("let's plan the architecture and milestones") == BehaviouralMode.PLAN
    assert detect_behavioural_mode("generate a coding agent prompt for cursor") == BehaviouralMode.BUILD
    assert detect_behavioural_mode("please critique my architecture and grill it") == BehaviouralMode.REVIEW
    assert detect_behavioural_mode("debug this TypeError from the stack trace") == BehaviouralMode.DEBUG


def test_mode_stickiness_does_not_restart_explore_from_build():
    mode = detect_behavioural_mode(
        "what about the ingest step?",
        current=BehaviouralMode.BUILD,
    )
    assert mode == BehaviouralMode.BUILD


def test_build_does_not_unnecessarily_switch_to_explore():
    resolved = resolve_project_mode(
        BehaviouralMode.BUILD,
        "ok, continue with the API handler",
    )
    assert resolved == BehaviouralMode.BUILD


def test_legacy_aliases_normalize():
    assert (
        resolve_project_mode("grill_review", "also check the auth layer")
        == BehaviouralMode.REVIEW
    )
    assert (
        detect_behavioural_mode("suggest me some NLP project ideas")
        == BehaviouralMode.PLAN
    )


def test_debug_uses_technical_evidence_in_validation_path():
    analysis = PrimaryAnalysis(
        reply="Root cause is likely a null config value near the parser boundary.",
        findings=[],
        state_patch=StatePatch(),
    )
    result = validate_analysis_for_mode(
        analysis,
        mode=BehaviouralMode.DEBUG,
        has_objective=True,
        readiness_ready=False,
    )
    assert result.ok


@pytest.mark.asyncio
async def test_continuity_across_messages(repo, settings, project):
    engine = build_engine(repo, settings)
    first = await engine.handle_message(
        project.id,
        "I want to build a cybersecurity log analysis platform.",
        behavioural_mode=BehaviouralMode.EXPLORE,
    )
    assert first.behavioural_mode == BehaviouralMode.EXPLORE

    second = await engine.handle_message(
        project.id,
        "Windows event logs.",
        behavioural_mode=BehaviouralMode.EXPLORE,
    )
    # Sticky / continued explore — should not jump to review without cues
    assert second.behavioural_mode == BehaviouralMode.EXPLORE
    assert second.project.objective or second.message.content

    third = await engine.handle_message(
        project.id,
        "Investigation assistance.",
        behavioural_mode=BehaviouralMode.PLAN,
    )
    assert third.behavioural_mode == BehaviouralMode.PLAN
    # Prior objective should still be present
    assert third.project.objective


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------


def test_agent_prompt_blocked_when_not_ready():
    project = ProjectState(name="Empty")
    result = compile_agent_prompt(project)
    assert result.blocked
    assert "blocked" in result.prompt.lower() or "resolve" in result.prompt.lower()


def test_agent_prompt_contains_context_constraints_and_acceptance():
    from app.projects.models import Constraint

    project = ProjectState(
        name="WinLog",
        objective="Help analysts investigate Windows event logs",
        problem_statement="Raw EVTX is hard to query during investigations",
        intended_users=["IR analysts"],
        success_criteria=["Analyst can load an EVTX and filter by Event ID"],
        scope_in=["EVTX ingest", "Normalized query UI"],
        scope_out=["Real-time detection engine"],
        tech_stack=["Python", "SQLite", "FastAPI"],
        constraints=[Constraint(text="Solo developer, 4-week MVP")],
        decisions=[
            Decision(
                title="Detection vs investigation",
                choice="Investigation assistance",
                rationale="User confirmed",
            )
        ],
        functional_requirements=[
            Requirement(
                text="Ingest Windows EVTX files",
                acceptance_criteria=["Sample EVTX loads without crash"],
            )
        ],
        non_functional_requirements=[
            Requirement(text="Runs on a single laptop", kind="non_functional"),
        ],
        rejected_approaches=[
            RejectedApproach(approach="Full SIEM clone", reason="Out of MVP")
        ],
        testing_notes="pytest for parsers; manual EVTX fixture check",
        architecture_notes="Batch ingest → normalize → query",
        data_model_notes="events(id, event_id, timestamp, raw_xml)",
    )
    result = compile_agent_prompt(project, agent="cursor")
    assert not result.blocked, result.block_reasons
    assert result.readiness.implementation_ready
    prompt = result.prompt.lower()
    assert "investigation assistance" in prompt
    assert "sqlite" in prompt or "python" in prompt
    assert "acceptance" in prompt
    assert "out of scope" in prompt or "prohibited" in prompt
    assert "verification" in prompt or "test" in prompt
    assert "full siem" in prompt
    assert "cursor" in prompt
    # Irrelevant chat history is not dumped into the agent prompt
    assert "recent_messages" not in prompt


def test_agent_prompt_force_includes_blockers():
    project = ProjectState(name="Empty")
    result = compile_agent_prompt(project, force=True)
    assert result.prompt
    # force bypasses readiness blocked flag (quality may still annotate)
    assert result.blocked is False or "quality" in (result.prompt or "").lower()
