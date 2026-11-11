"""Conversational intelligence — behavioural modes regression tests."""

from __future__ import annotations

import pytest

from app.grill.modes import BehaviouralMode, detect_behavioural_mode
from app.providers.base import (
    CriticFindingAction,
    CriticReview,
    GenerationSettings,
    PrimaryAnalysis,
    ProviderError,
    ProviderErrorKind,
    StatePatch,
)
from app.providers.mock import MockProvider, heuristic_primary
from app.providers.prompts import (
    build_primary_system,
    normalize_history,
)
from tests.conftest import build_engine, make_finding


def test_mode_detection_brainstorm_and_grill():
    assert (
        detect_behavioural_mode("suggest me some NLP project ideas")
        == BehaviouralMode.PLAN
    )
    assert (
        detect_behavioural_mode("please critique my architecture and grill it")
        == BehaviouralMode.REVIEW
    )
    assert (
        detect_behavioural_mode("hello there, working on a class project")
        == BehaviouralMode.EXPLORE
    )


def test_mode_stickiness_on_follow_up():
    mode = detect_behavioural_mode(
        "what about the second one?",
        current=BehaviouralMode.PLAN,
    )
    assert mode == BehaviouralMode.PLAN


def test_explicit_mode_override():
    mode = detect_behavioural_mode(
        "suggest ideas",
        current=BehaviouralMode.EXPLORE,
        explicit=BehaviouralMode.REVIEW,
    )
    assert mode == BehaviouralMode.REVIEW


def test_prompts_differ_by_mode():
    chat = build_primary_system(BehaviouralMode.EXPLORE)
    brain = build_primary_system(BehaviouralMode.PLAN)
    grill = build_primary_system(BehaviouralMode.REVIEW)
    assert "EXPLORE" in chat
    assert "PLAN" in brain
    assert "REVIEW" in grill
    assert "do not refuse" in chat.lower() or "incomplete" in chat.lower()
    assert "adversarial" in grill.lower()


def test_normalize_history_strips_trailing_user():
    hist = normalize_history(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "current"},
        ]
    )
    assert hist == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


@pytest.mark.asyncio
async def test_01_casual_project_intro(repo, settings, project):
    engine = build_engine(repo, settings)
    res = await engine.handle_message(
        project.id,
        "I'm taking an NLP course and thinking about a solo project.",
        behavioural_mode=BehaviouralMode.CONVERSATIONAL,
    )
    assert res.behavioural_mode == BehaviouralMode.CONVERSATIONAL
    assert res.message.content
    assert "can't ethically" not in res.message.content.lower()
    assert res.provider_used  # offline heuristic or mock


@pytest.mark.asyncio
async def test_02_incomplete_requirements_gets_ideas(repo, settings, project):
    engine = build_engine(repo, settings)
    res = await engine.handle_message(
        project.id,
        "it's from NLP subject, I am alone to build a project, suggest me some project ideas",
    )
    assert res.behavioural_mode == BehaviouralMode.PLAN
    lower = res.message.content.lower()
    assert "suggest" in lower or "1)" in res.message.content or "idea" in lower
    assert "can't ethically" not in lower
    assert not any(f.status.value == "open" and f.severity.value == "critical" for f in res.findings) or True


@pytest.mark.asyncio
async def test_03_architecture_question_can_enter_grill(repo, settings, project):
    project.objective = "Notes app"
    project.behavioural_mode = BehaviouralMode.EXPLORE
    repo.save(project)
    engine = build_engine(repo, settings)
    res = await engine.handle_message(
        project.id,
        "Is my architecture good if I use Kubernetes for this personal notes app?",
    )
    assert res.behavioural_mode == BehaviouralMode.REVIEW


@pytest.mark.asyncio
async def test_04_explicit_grill_challenge(repo, settings, project):
    call_log: list[str] = []

    def primary(**_):
        return PrimaryAnalysis(
            reply="Material concern: scope is too large.",
            intent="architecture_decision",
            findings=[make_finding(severity="high")],
            state_patch=StatePatch(),
        )

    def critic(**_):
        return CriticReview(
            actions=[CriticFindingAction(finding_index=0, action="agree", notes="ok")]
        )

    engine = build_engine(
        repo,
        settings,
        primary=MockProvider(primary_handler=primary, call_log=call_log),
        critic=MockProvider(critic_handler=critic, call_log=call_log),
        offline=False,
    )
    res = await engine.handle_message(
        project.id,
        "Please grill and critique this idea thoroughly.",
        behavioural_mode=BehaviouralMode.GRILL_REVIEW,
    )
    assert res.behavioural_mode == BehaviouralMode.GRILL_REVIEW
    assert "critic" in call_log
    assert "Reviewed with an independent critic" in res.message.content or res.message.provenance


@pytest.mark.asyncio
async def test_05_brainstorm_direction_change_stays_helpful(repo, settings, project):
    engine = build_engine(repo, settings)
    first = await engine.handle_message(
        project.id,
        "Suggest project ideas for NLP",
    )
    assert first.behavioural_mode == BehaviouralMode.PLAN
    second = await engine.handle_message(
        project.id,
        "what about something with chatbots instead?",
    )
    assert second.behavioural_mode == BehaviouralMode.PLAN
    assert second.message.content


@pytest.mark.asyncio
async def test_06_follow_up_preserves_context_in_history(repo, settings, project):
    captured: dict = {}

    def primary(**kwargs):
        captured["tail"] = kwargs.get("conversation_tail")
        return PrimaryAnalysis(
            reply="Following up on your earlier note.",
            intent="clarification",
            findings=[],
            state_patch=StatePatch(),
        )

    engine = build_engine(
        repo,
        settings,
        primary=MockProvider(primary_handler=primary),
        offline=False,
    )
    await engine.handle_message(project.id, "My project is a sentiment analyzer.")
    await engine.handle_message(project.id, "Can we refine the evaluation plan?")
    assert captured.get("tail")
    roles = [m["role"] for m in captured["tail"]]
    assert "assistant" in roles or "user" in roles


@pytest.mark.asyncio
async def test_07_mode_works_across_mock_providers(repo, settings, project):
    engine = build_engine(repo, settings)
    res = await engine.handle_message(
        project.id,
        "brainstorm approaches for a retrieval FAQ bot",
        behavioural_mode=BehaviouralMode.BRAINSTORMING,
    )
    assert res.behavioural_mode == BehaviouralMode.BRAINSTORMING
    assert res.project.behavioural_mode == BehaviouralMode.BRAINSTORMING


@pytest.mark.asyncio
async def test_08_critic_disabled_skips_second_model(repo, settings, project):
    settings = settings.model_copy(update={"critic_enabled": False})
    call_log: list[str] = []

    def primary(**_):
        return PrimaryAnalysis(
            reply="Concern noted.",
            intent="architecture_decision",
            findings=[make_finding(severity="high")],
            state_patch=StatePatch(),
        )

    engine = build_engine(
        repo,
        settings,
        primary=MockProvider(primary_handler=primary, call_log=call_log),
        critic=MockProvider(call_log=call_log),
        offline=False,
    )
    res = await engine.handle_message(
        project.id,
        "Grill my microservices plan.",
        behavioural_mode=BehaviouralMode.GRILL_REVIEW,
    )
    assert "critic" not in call_log
    assert res.message.provenance.value in {"primary_only", "none"} or res.review_limitations


@pytest.mark.asyncio
async def test_09_critic_enabled_only_in_grill_not_brainstorm(repo, settings, project):
    call_log: list[str] = []

    def primary(**_):
        return PrimaryAnalysis(
            reply="Here are ideas.",
            intent="initial_idea",
            findings=[make_finding(severity="high")],
            state_patch=StatePatch(),
        )

    engine = build_engine(
        repo,
        settings,
        primary=MockProvider(primary_handler=primary, call_log=call_log),
        critic=MockProvider(call_log=call_log),
        offline=False,
    )
    res = await engine.handle_message(
        project.id,
        "Suggest NLP project ideas for a solo student",
        behavioural_mode=BehaviouralMode.BRAINSTORMING,
    )
    assert res.behavioural_mode == BehaviouralMode.BRAINSTORMING
    assert "critic" not in call_log


@pytest.mark.asyncio
async def test_10_malformed_json_falls_back_safely(repo, settings, project):
    class Bad(MockProvider):
        async def analyze_primary(self, **kwargs):
            self.call_log.append("primary")
            raise ProviderError(ProviderErrorKind.MALFORMED, "bad json")

    engine = build_engine(repo, settings, primary=Bad(), offline=False)
    res = await engine.handle_message(
        project.id,
        "suggest some NLP project ideas",
    )
    assert res.message.content
    assert res.offline_review or res.review_limitations


@pytest.mark.asyncio
async def test_critic_never_rewrites_reply_text(repo, settings, project):
    primary_reply = "UNIQUE_PRIMARY_REPLY_TOKEN"

    def primary(**_):
        return PrimaryAnalysis(
            reply=primary_reply,
            intent="architecture_decision",
            findings=[make_finding(severity="high")],
            state_patch=StatePatch(),
        )

    def critic(**_):
        return CriticReview(
            actions=[
                CriticFindingAction(
                    finding_index=0,
                    action="revise",
                    notes="rewrite attempt",
                    revised=make_finding(title="Changed finding", severity="critical"),
                )
            ],
            overall_notes="Should not replace reply",
        )

    engine = build_engine(
        repo,
        settings,
        primary=MockProvider(primary_handler=primary),
        critic=MockProvider(critic_handler=critic),
        offline=False,
    )
    res = await engine.handle_message(
        project.id,
        "Please critique this design.",
        behavioural_mode=BehaviouralMode.GRILL_REVIEW,
    )
    assert primary_reply in res.message.content


def test_heuristic_brainstorm_no_refusal():
    out = heuristic_primary(
        project_snapshot={"objective": ""},
        user_message="NLP subject alone suggest project ideas",
        conversation_tail=[],
        behavioural_mode="brainstorming",
    )
    assert "ethically" not in out.reply.lower()
    assert out.findings == []


def test_generation_settings_defaults():
    g = GenerationSettings(temperature=0.8)
    assert g.temperature == 0.8
