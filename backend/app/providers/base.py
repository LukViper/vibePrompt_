"""Provider-independent model interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProviderErrorKind(str, Enum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    MALFORMED = "malformed"
    UNAVAILABLE = "unavailable"
    INVALID_REQUEST = "invalid_request"
    OTHER = "other"


# Failover-worthy: try the next eligible provider (do not loop forever on one).
FAILOVER_KINDS = frozenset(
    {
        ProviderErrorKind.TIMEOUT,
        ProviderErrorKind.RATE_LIMIT,
        ProviderErrorKind.UNAVAILABLE,
        ProviderErrorKind.AUTH,
        ProviderErrorKind.MALFORMED,
        ProviderErrorKind.INVALID_REQUEST,
        ProviderErrorKind.OTHER,
    }
)

# Same-provider retries only for transient availability issues.
SAME_PROVIDER_RETRY_KINDS = frozenset(
    {
        ProviderErrorKind.TIMEOUT,
        ProviderErrorKind.RATE_LIMIT,
        ProviderErrorKind.UNAVAILABLE,
    }
)


class ProviderError(Exception):
    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str,
        *,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retry_after = retry_after

    @property
    def is_failover_worthy(self) -> bool:
        return self.kind in FAILOVER_KINDS

    @property
    def allows_same_provider_retry(self) -> bool:
        return self.kind in SAME_PROVIDER_RETRY_KINDS


class CandidateFinding(BaseModel):
    title: str
    challenged_claim: str
    reasoning: str
    evidence: list[str] = Field(default_factory=list)
    assumptions_to_verify: list[str] = Field(default_factory=list)
    severity: str = "medium"
    confidence: float = 0.5
    potential_impact: str = ""
    recommended_next_step: str = ""
    invalidation_criteria: str = ""


class StatePatch(BaseModel):
    """Proposed project-state updates. Backend validates before applying."""

    objective: str | None = None
    description: str | None = None
    problem_statement: str | None = None
    intended_users: list[str] | None = None
    success_criteria: list[str] | None = None
    add_functional_requirements: list[str] | None = None
    add_non_functional_requirements: list[str] | None = None
    add_scope_in: list[str] | None = None
    add_scope_out: list[str] | None = None
    add_constraints: list[dict[str, str]] | None = None
    add_decisions: list[dict[str, Any]] | None = None
    add_assumptions: list[str] | None = None
    add_open_questions: list[str] | None = None
    add_preferences: list[str] | None = None
    add_rejected_approaches: list[dict[str, str]] | None = None
    add_known_risks: list[str] | None = None
    add_outstanding_tasks: list[str] | None = None
    add_completed_milestones: list[str] | None = None
    tech_stack: list[str] | None = None
    add_technology_selections: list[dict[str, Any]] | None = None
    # When true, conflicting tech in the same category may replace the active selection
    replace_technology: bool | None = None
    architecture_notes: str | None = None
    # auto | append | replace — controls long-form note updates
    architecture_notes_mode: str | None = None
    data_model_notes: str | None = None
    data_model_notes_mode: str | None = None
    security_notes: str | None = None
    security_notes_mode: str | None = None
    testing_notes: str | None = None
    testing_notes_mode: str | None = None
    milestones: list[str] | None = None
    implementation_status: str | None = None


class PrimaryAnalysis(BaseModel):
    reply: str
    intent: str = "general"
    findings: list[CandidateFinding] = Field(default_factory=list)
    most_important_question: str | None = None
    state_patch: StatePatch = Field(default_factory=StatePatch)
    raw_notes: str = ""


class CriticFindingAction(BaseModel):
    finding_index: int | None = None
    action: str  # agree | disagree | revise | add_risk | insufficient_evidence
    revised: CandidateFinding | None = None
    notes: str = ""


class CriticReview(BaseModel):
    actions: list[CriticFindingAction] = Field(default_factory=list)
    overall_notes: str = ""
    insufficient_context: bool = False


class GenerationSettings(BaseModel):
    """Provider-agnostic generation knobs. Adapters map to supported API fields."""

    temperature: float = 0.6
    max_output_tokens: int | None = None
    top_p: float | None = None
    skill_knowledge_block: str | None = None
    review_intensity: str = "normal"


class ModelProvider(ABC):
    name: str

    @abstractmethod
    async def analyze_primary(
        self,
        *,
        project_snapshot: dict[str, Any],
        user_message: str,
        conversation_tail: list[dict[str, str]],
        behavioural_mode: str = "conversational",
        generation: GenerationSettings | None = None,
    ) -> PrimaryAnalysis:
        raise NotImplementedError

    @abstractmethod
    async def critique(
        self,
        *,
        project_snapshot: dict[str, Any],
        user_message: str,
        candidate_findings: list[CandidateFinding],
        primary_reply: str,
        generation: GenerationSettings | None = None,
    ) -> CriticReview:
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError
