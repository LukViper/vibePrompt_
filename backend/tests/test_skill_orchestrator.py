"""Skill orchestration selection tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.grill.modes import BehaviouralMode
from app.knowledge.store import KnowledgeStore
from app.skills.orchestrator import build_orchestration_context, select_skill_slugs
from app.skills.registry import SkillRegistry


@pytest.fixture()
def registry(tmp_path: Path) -> SkillRegistry:
    store = KnowledgeStore(str(tmp_path / "db.sqlite"), skills_root=tmp_path / "skills")
    return SkillRegistry(store)


def test_architecture_message_selects_technical_skill():
    plan = select_skill_slugs(
        mode=BehaviouralMode.CONVERSATIONAL,
        user_message="Help me design the architecture and tech stack for a cybersecurity platform.",
    )
    assert "technical_architecture" in plan.selected_slugs
    assert plan.reasons["technical_architecture"] == "message_cue"


def test_grill_mode_includes_grill_skill():
    plan = select_skill_slugs(
        mode=BehaviouralMode.GRILL_REVIEW,
        user_message="What do you think?",
    )
    assert "grill" in plan.selected_slugs


def test_prompt_message_selects_prompt_engineering():
    plan = select_skill_slugs(
        mode=BehaviouralMode.CONVERSATIONAL,
        user_message="Write a coding agent prompt with acceptance criteria.",
    )
    assert "prompt_engineering" in plan.selected_slugs


def test_user_selected_skills_come_first():
    plan = select_skill_slugs(
        mode=BehaviouralMode.CONVERSATIONAL,
        user_message="hello",
        user_selected=["project_planning"],
    )
    assert plan.selected_slugs[0] == "project_planning"
    assert plan.reasons["project_planning"] == "user_selected"


def test_build_orchestration_injects_compact_block(registry: SkillRegistry):
    plan = build_orchestration_context(
        registry,
        registry.store,
        mode=BehaviouralMode.BRAINSTORMING,
        user_message="Brainstorm alternative approaches for onboarding.",
    )
    assert plan.prompt_block
    assert "SKILL_ORCHESTRATION" in plan.prompt_block or "SKILL_KNOWLEDGE" in plan.prompt_block
    assert len(plan.prompt_block) < 5000
    assert "brainstorm" in plan.selected_slugs
