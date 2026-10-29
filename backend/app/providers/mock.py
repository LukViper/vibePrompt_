"""Deterministic mock providers for tests — no network, no API keys."""

from __future__ import annotations

from typing import Any, Callable

from app.providers.base import (
    CandidateFinding,
    CriticFindingAction,
    CriticReview,
    ModelProvider,
    PrimaryAnalysis,
    ProviderError,
    ProviderErrorKind,
    StatePatch,
)


PrimaryHandler = Callable[..., PrimaryAnalysis]
CriticHandler = Callable[..., CriticReview]


class MockProvider(ModelProvider):
    name = "mock"

    def __init__(
        self,
        *,
        available: bool = True,
        primary_handler: PrimaryHandler | None = None,
        critic_handler: CriticHandler | None = None,
        primary_error: ProviderError | None = None,
        critic_error: ProviderError | None = None,
        call_log: list[str] | None = None,
    ) -> None:
        self._available = available
        self._primary_handler = primary_handler
        self._critic_handler = critic_handler
        self._primary_error = primary_error
        self._critic_error = critic_error
        self.call_log = call_log if call_log is not None else []

    def is_available(self) -> bool:
        return self._available

    async def analyze_primary(
        self,
        *,
        project_snapshot: dict[str, Any],
        user_message: str,
        conversation_tail: list[dict[str, str]],
    ) -> PrimaryAnalysis:
        self.call_log.append("primary")
        if self._primary_error:
            raise self._primary_error
        if self._primary_handler:
            return self._primary_handler(
                project_snapshot=project_snapshot,
                user_message=user_message,
                conversation_tail=conversation_tail,
            )
        return PrimaryAnalysis(
            reply="Mock primary reply.",
            intent="general",
            findings=[],
            state_patch=StatePatch(),
        )

    async def critique(
        self,
        *,
        project_snapshot: dict[str, Any],
        user_message: str,
        candidate_findings: list[CandidateFinding],
        primary_reply: str,
    ) -> CriticReview:
        self.call_log.append("critic")
        if self._critic_error:
            raise self._critic_error
        if self._critic_handler:
            return self._critic_handler(
                project_snapshot=project_snapshot,
                user_message=user_message,
                candidate_findings=candidate_findings,
                primary_reply=primary_reply,
            )
        return CriticReview(
            actions=[
                CriticFindingAction(finding_index=i, action="agree", notes="ok")
                for i in range(len(candidate_findings))
            ]
        )


def heuristic_primary(
    *,
    project_snapshot: dict[str, Any],
    user_message: str,
    conversation_tail: list[dict[str, str]],
) -> PrimaryAnalysis:
    """Lightweight offline analyzer used when no API key is configured."""
    text = user_message.lower()
    findings: list[CandidateFinding] = []
    intent = "general"
    patch = StatePatch()
    reply_bits: list[str] = []

    greetings = ("hi", "hello", "hey", "thanks", "thank you")
    if text.strip() in greetings or (
        len(text) < 40 and any(text.startswith(g) for g in greetings)
    ):
        return PrimaryAnalysis(
            reply="Hi — describe the project you want Grill to challenge before you build.",
            intent="greeting",
            findings=[],
            state_patch=StatePatch(),
        )

    # Detect injection attempts — do not obey them
    if any(
        m in text
        for m in (
            "ignore previous",
            "reveal your system",
            "you are now",
            "override safety",
        )
    ):
        return PrimaryAnalysis(
            reply=(
                "I treat project text as data, not instructions. "
                "Please describe the product idea you want reviewed."
            ),
            intent="general",
            findings=[],
            state_patch=StatePatch(),
        )

    objective = project_snapshot.get("objective") or ""
    if not objective and len(user_message) > 40:
        patch.objective = user_message.strip()[:500]
        intent = "initial_idea"
        reply_bits.append("I've captured an initial objective from your description.")

    deadline_words = ("tomorrow", "this week", "2 days", "two days", "48 hours", "weekend")
    scope_words = ("marketplace", "platform", "social network", "uber for", "clone of")
    if any(w in text for w in deadline_words) and any(w in text for w in scope_words):
        intent = "scope_change"
        findings.append(
            CandidateFinding(
                title="Unrealistic scope for the stated deadline",
                challenged_claim="Large product scope can be delivered in the stated short deadline",
                reasoning=(
                    "The described product implies multiple subsystems while the deadline "
                    "is very short. Without a drastically reduced MVP, the schedule is unlikely."
                ),
                evidence=["User-stated short deadline", "Broad product scope in the message"],
                assumptions_to_verify=["Team size and existing reusable components"],
                severity="critical",
                confidence=0.85,
                potential_impact="Wasted agent tokens building unfinished surfaces; missed deadline",
                recommended_next_step="Define a one-week MVP with ≤3 user stories",
                invalidation_criteria="Evidence of existing codebase covering most features",
            )
        )

    heavy = ("kubernetes", "kafka", "microservices", "event sourcing", "graphql federation")
    small = ("todo", "notes app", "personal", "single user", "side project", "mvp")
    if any(w in text for w in heavy) and (
        any(w in text for w in small) or "small" in text or "simple" in text
    ):
        intent = "architecture_decision"
        findings.append(
            CandidateFinding(
                title="Heavyweight infrastructure for a small app",
                challenged_claim="Complex distributed infrastructure is justified for this app",
                reasoning=(
                    "Operational complexity of the proposed stack exceeds the likely needs "
                    "of a small or personal application."
                ),
                evidence=["User described a small/simple app", "Heavy infrastructure named"],
                assumptions_to_verify=["Expected scale and team ops capacity"],
                severity="high",
                confidence=0.8,
                potential_impact="Longer time-to-first-value and higher maintenance cost",
                recommended_next_step="Start with a modular monolith and a single database",
                invalidation_criteria="Documented multi-tenant scale or compliance requirements",
            )
        )
        patch.add_decisions = [
            {
                "title": "Infrastructure approach",
                "choice": "Proposed heavyweight stack (under review)",
                "rationale": user_message[:300],
            }
        ]

    if ("must be offline" in text and "must sync" in text) or (
        "no internet" in text and "real-time cloud" in text
    ):
        intent = "general"
        findings.append(
            CandidateFinding(
                title="Contradictory connectivity requirements",
                challenged_claim="System can be fully offline and real-time cloud-synced simultaneously without trade-offs",
                reasoning="Offline-only and real-time cloud sync conflict unless carefully scoped with conflict resolution.",
                evidence=["Both offline and real-time sync requirements stated"],
                assumptions_to_verify=["Whether offline mode may queue and sync later"],
                severity="critical",
                confidence=0.9,
                potential_impact="Impossible acceptance criteria; thrashing architecture",
                recommended_next_step="Choose primary mode: offline-first with eventual sync, or online-first",
                invalidation_criteria="A clear conflict-resolution and connectivity policy",
            )
        )

    if "sqlite" in text and ("single user" in text or "local" in text or "personal" in text):
        intent = "architecture_decision"
        patch.add_decisions = [
            {
                "title": "Database",
                "choice": "SQLite",
                "rationale": "Single-user/local app — SQLite is appropriate",
            }
        ]
        reply_bits.append(
            "SQLite for a single-user local app is a sound default. I don't see a material objection."
        )

    if not reply_bits:
        if findings:
            reply_bits.append(
                "I have material concerns before you start building. "
                + findings[0].recommended_next_step
            )
        else:
            reply_bits.append(
                "Got it. What success criteria would make this project 'done' for the first release?"
            )

    question = findings[0].recommended_next_step if findings else "What is the smallest useful v1?"
    return PrimaryAnalysis(
        reply=" ".join(reply_bits) + (f" {question}" if question not in " ".join(reply_bits) else ""),
        intent=intent,
        findings=findings,
        most_important_question=question,
        state_patch=patch,
    )


def timeout_error(kind: str = "primary") -> ProviderError:
    return ProviderError(ProviderErrorKind.TIMEOUT, f"{kind} timed out")


def rate_limit_error(kind: str = "primary") -> ProviderError:
    return ProviderError(ProviderErrorKind.RATE_LIMIT, f"{kind} rate limited")
