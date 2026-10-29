"""Deterministic review policy — decides when to call models / critic."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.config import ReviewIntensity
from app.projects.models import MessageIntent, ProjectState


class ReviewAction(str, Enum):
    CONVERSATION_ONLY = "conversation_only"
    PRIMARY_ONLY = "primary_only"
    TWO_MODEL = "two_model"
    REASSESS = "reassess"


@dataclass
class PolicyDecision:
    action: ReviewAction
    reason: str
    detected_intent: MessageIntent


_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|good (morning|afternoon|evening))[\s!.]*$",
    re.I,
)
_EVIDENCE_RE = re.compile(
    r"\b(because|evidence|benchmark|measured|we already|existing|proof|data shows|we tested)\b",
    re.I,
)
_INSIST_RE = re.compile(
    r"\b(just do it|i insist|ignore that|doesn't matter|we'll figure it out later|trust me)\b",
    re.I,
)
_RESOLVE_RE = re.compile(
    r"\b(resolved|we fixed|accept(ing)? the risk|mark as resolved|reject(ing)? that finding)\b",
    re.I,
)
_ARCH_RE = re.compile(
    r"\b(kubernetes|kafka|microservice|postgres|sqlite|mongodb|graphql|rest api|architecture|tech stack)\b",
    re.I,
)
_SCOPE_RE = re.compile(
    r"\b(deadline|by tomorrow|this week|launch in|mvp|also need|scope|must also|add feature)\b",
    re.I,
)


def detect_intent(message: str, project: ProjectState) -> MessageIntent:
    text = message.strip()
    if _GREETING_RE.match(text) or (len(text) < 24 and text.lower() in {"hi", "hello", "hey"}):
        return MessageIntent.GREETING
    if _RESOLVE_RE.search(text):
        return MessageIntent.RESOLUTION
    if _INSIST_RE.search(text) and not _EVIDENCE_RE.search(text):
        return MessageIntent.INSISTENCE
    if _EVIDENCE_RE.search(text):
        return MessageIntent.EVIDENCE
    if not project.objective and len(text) > 40:
        return MessageIntent.INITIAL_IDEA
    if _ARCH_RE.search(text):
        return MessageIntent.ARCHITECTURE_DECISION
    if _SCOPE_RE.search(text):
        return MessageIntent.SCOPE_CHANGE
    if text.endswith("?"):
        return MessageIntent.QUESTION
    if len(text) < 80 and project.objective:
        return MessageIntent.CLARIFICATION
    return MessageIntent.GENERAL


def decide_review_policy(
    *,
    message: str,
    project: ProjectState,
    intensity: ReviewIntensity = "normal",
    critic_available: bool = True,
) -> PolicyDecision:
    intent = detect_intent(message, project)

    if intent == MessageIntent.GREETING:
        return PolicyDecision(ReviewAction.CONVERSATION_ONLY, "greeting", intent)

    if intent == MessageIntent.CLARIFICATION and intensity == "low":
        return PolicyDecision(ReviewAction.CONVERSATION_ONLY, "trivial clarification", intent)

    # Resolved/rejected findings without new evidence → don't regenerate
    if intent == MessageIntent.RESOLUTION and not _EVIDENCE_RE.search(message):
        return PolicyDecision(
            ReviewAction.PRIMARY_ONLY,
            "lifecycle update without new evidence",
            intent,
        )

    # Insistence without evidence → primary only; do not withdraw findings
    if intent == MessageIntent.INSISTENCE:
        return PolicyDecision(
            ReviewAction.PRIMARY_ONLY,
            "insistence without evidence",
            intent,
        )

    material = intent in {
        MessageIntent.INITIAL_IDEA,
        MessageIntent.ARCHITECTURE_DECISION,
        MessageIntent.SCOPE_CHANGE,
        MessageIntent.EVIDENCE,
    }

    if intensity == "high":
        material = material or intent in {MessageIntent.GENERAL, MessageIntent.QUESTION}

    if material and critic_available and intensity != "low":
        action = ReviewAction.REASSESS if intent == MessageIntent.EVIDENCE else ReviewAction.TWO_MODEL
        return PolicyDecision(action, f"material:{intent.value}", intent)

    if material or intensity != "low":
        return PolicyDecision(ReviewAction.PRIMARY_ONLY, f"primary:{intent.value}", intent)

    return PolicyDecision(ReviewAction.CONVERSATION_ONLY, "low intensity non-material", intent)


def findings_material(findings_count: int, severity_max: str | None) -> bool:
    if findings_count <= 0:
        return False
    if severity_max in {"critical", "high"}:
        return True
    return findings_count > 0
