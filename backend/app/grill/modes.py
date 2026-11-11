"""Behavioural modes: explore, plan, build, review, debug (+ legacy aliases)."""

from __future__ import annotations

import re
from enum import Enum


class BehaviouralMode(str, Enum):
    # Canonical mentoring modes
    EXPLORE = "explore"
    PLAN = "plan"
    BUILD = "build"
    REVIEW = "review"
    DEBUG = "debug"
    # Legacy aliases — persisted projects / older API clients
    CONVERSATIONAL = "conversational"
    BRAINSTORMING = "brainstorming"
    GRILL_REVIEW = "grill_review"


MODE_LABELS = {
    BehaviouralMode.EXPLORE: "Explore",
    BehaviouralMode.PLAN: "Plan",
    BehaviouralMode.BUILD: "Build",
    BehaviouralMode.REVIEW: "Review",
    BehaviouralMode.DEBUG: "Debug",
    BehaviouralMode.CONVERSATIONAL: "Conversation",
    BehaviouralMode.BRAINSTORMING: "Brainstorming",
    BehaviouralMode.GRILL_REVIEW: "Grill review",
}

DEFAULT_TEMPERATURES: dict[BehaviouralMode, float] = {
    BehaviouralMode.EXPLORE: 0.6,
    BehaviouralMode.PLAN: 0.7,
    BehaviouralMode.BUILD: 0.35,
    BehaviouralMode.REVIEW: 0.3,
    BehaviouralMode.DEBUG: 0.3,
    BehaviouralMode.CONVERSATIONAL: 0.6,
    BehaviouralMode.BRAINSTORMING: 0.8,
    BehaviouralMode.GRILL_REVIEW: 0.3,
}

_LEGACY_TO_CANONICAL = {
    BehaviouralMode.CONVERSATIONAL: BehaviouralMode.EXPLORE,
    BehaviouralMode.BRAINSTORMING: BehaviouralMode.PLAN,
    BehaviouralMode.GRILL_REVIEW: BehaviouralMode.REVIEW,
}


def canonical_mode(mode: BehaviouralMode | str | None) -> BehaviouralMode:
    """Map legacy modes onto the five mentoring modes."""
    parsed = parse_mode(mode) if not isinstance(mode, BehaviouralMode) else mode
    if parsed is None:
        return BehaviouralMode.EXPLORE
    return _LEGACY_TO_CANONICAL.get(parsed, parsed)


_EXPLICIT_EXPLORE = re.compile(
    r"\b(just chat|normal (mode|conversation)|stop (grilling|critiquing)|"
    r"be (more )?friendly|casual (mode|chat)|switch to (conversation|explore)|"
    r"let'?s explore|understand the problem|who is (the |my )?user|"
    r"what('s| is) the (real )?problem)\b",
    re.I,
)
_EXPLICIT_PLAN = re.compile(
    r"\b(brainstorm(ing)?|suggest(ions)?|project ideas|give me ideas|"
    r"what should i (build|make)|help me think of|alternatives|"
    r"approaches|ideate|propose (some )?options|let'?s plan|"
    r"implementation (plan|strategy)|architecture (plan|options)|"
    r"tech stack|milestones|break (this|it) (down|into))\b",
    re.I,
)
_EXPLICIT_BUILD = re.compile(
    r"\b(build (it|this|the)|implement(ation)?|write (the )?code|"
    r"coding agent|generate (a |the )?(prompt|spec)|give me (a )?prompt|"
    r"cursor prompt|claude code|start coding|acceptance criteria|"
    r"implementation instructions)\b",
    re.I,
)
_EXPLICIT_REVIEW = re.compile(
    r"\b(grill|critique|criticize|challenge (this|my|the)|evaluate|"
    r"review (this|my)|tear (it|this) apart|what's wrong|"
    r"is (this|my) (architecture|design|stack|approach) (good|sound|solid)|"
    r"adversarial|find (the )?risks|stress[- ]test|code review)\b",
    re.I,
)
_EXPLICIT_DEBUG = re.compile(
    r"\b(debug|fix (this|the|my)|broken|error|exception|stack trace|"
    r"traceback|not working|fails? to|bug|root cause|why (is|does|did)|"
    r"logs? (show|say)|crash(ed|es|ing)?)\b",
    re.I,
)
_FOLLOW_UP = re.compile(
    r"^\s*(what about|also|and |how about|ok,? (then|what)|"
    r"tell me more|another|yes|yeah|go on|continue|that one|"
    r"the second|option \d)\b",
    re.I,
)


def parse_mode(value: str | BehaviouralMode | None) -> BehaviouralMode | None:
    if value is None:
        return None
    if isinstance(value, BehaviouralMode):
        return value
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "explore": BehaviouralMode.EXPLORE,
        "conversation": BehaviouralMode.EXPLORE,
        "conversational": BehaviouralMode.CONVERSATIONAL,
        "chat": BehaviouralMode.EXPLORE,
        "plan": BehaviouralMode.PLAN,
        "brainstorm": BehaviouralMode.PLAN,
        "brainstorming": BehaviouralMode.BRAINSTORMING,
        "ideas": BehaviouralMode.PLAN,
        "build": BehaviouralMode.BUILD,
        "implement": BehaviouralMode.BUILD,
        "implementation": BehaviouralMode.BUILD,
        "review": BehaviouralMode.REVIEW,
        "grill": BehaviouralMode.REVIEW,
        "grill_review": BehaviouralMode.GRILL_REVIEW,
        "critique": BehaviouralMode.REVIEW,
        "debug": BehaviouralMode.DEBUG,
        "fix": BehaviouralMode.DEBUG,
        "troubleshoot": BehaviouralMode.DEBUG,
    }
    return aliases.get(normalized)


def detect_behavioural_mode(
    message: str,
    *,
    current: BehaviouralMode | None = None,
    explicit: BehaviouralMode | None = None,
) -> BehaviouralMode:
    """Deterministic mode selection. Explicit override wins; otherwise sticky + cues."""
    if explicit is not None:
        # Preserve client-provided value (including legacy aliases)
        return explicit

    text = message.strip()
    if _EXPLICIT_DEBUG.search(text):
        return BehaviouralMode.DEBUG
    if _EXPLICIT_REVIEW.search(text):
        return BehaviouralMode.REVIEW
    if _EXPLICIT_BUILD.search(text):
        return BehaviouralMode.BUILD
    if _EXPLICIT_PLAN.search(text):
        return BehaviouralMode.PLAN
    if _EXPLICIT_EXPLORE.search(text):
        return BehaviouralMode.EXPLORE

    # Stickiness migrates legacy modes onto the canonical five
    sticky = canonical_mode(current) if current else None

    # Stickiness for short follow-ups — do not thrash modes mid-thread
    if sticky and _FOLLOW_UP.search(text) and len(text) < 160:
        return sticky
    if sticky and len(text) < 100 and sticky != BehaviouralMode.EXPLORE:
        if not text.endswith("?") or sticky == BehaviouralMode.PLAN:
            return sticky

    if sticky:
        return sticky
    return BehaviouralMode.EXPLORE


def resolve_project_mode(
    current_mode: BehaviouralMode | str | None,
    message: str,
    *,
    explicit: BehaviouralMode | None = None,
) -> BehaviouralMode:
    current = parse_mode(current_mode)
    return detect_behavioural_mode(message, current=current, explicit=explicit)


def temperature_for_mode(
    mode: BehaviouralMode,
    *,
    conversational: float = 0.6,
    brainstorming: float = 0.8,
    grill_review: float = 0.3,
    explore: float | None = None,
    plan: float | None = None,
    build: float = 0.35,
    review: float | None = None,
    debug: float = 0.3,
) -> float:
    canon = canonical_mode(mode)
    mapping = {
        BehaviouralMode.EXPLORE: explore if explore is not None else conversational,
        BehaviouralMode.PLAN: plan if plan is not None else brainstorming,
        BehaviouralMode.BUILD: build,
        BehaviouralMode.REVIEW: review if review is not None else grill_review,
        BehaviouralMode.DEBUG: debug,
        BehaviouralMode.CONVERSATIONAL: conversational,
        BehaviouralMode.BRAINSTORMING: brainstorming,
        BehaviouralMode.GRILL_REVIEW: grill_review,
    }
    return mapping.get(mode, mapping[canon])


def should_run_critic(mode: BehaviouralMode | str) -> bool:
    return canonical_mode(mode) == BehaviouralMode.REVIEW
