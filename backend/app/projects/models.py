"""Domain models for project state, findings, and conversation."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.grill.modes import BehaviouralMode
from app.grill.notes import NoteRevision
from app.grill.tech import TechnologySelection


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "") -> str:
    raw = uuid4().hex[:12]
    return f"{prefix}{raw}" if prefix else raw


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ACCEPTED_RISK = "accepted_risk"
    REJECTED = "rejected"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    INVALIDATED = "invalidated"


class AssumptionClassification(str, Enum):
    """Assumption challenger labels — never treat AI advice as user-approved."""

    VERIFIED = "verified"
    USER_PROVIDED = "user_provided"
    REASONABLE_INFERENCE = "reasonable_inference"
    UNVERIFIED = "unverified"
    UNSUPPORTED = "unsupported"


class DecisionStatus(str, Enum):
    """Decision register statuses (brief §7). Legacy aliases normalized at apply-time."""

    CONFIRMED = "confirmed"
    PROVISIONALLY_ACCEPTED = "provisionally_accepted"
    PROPOSED = "proposed"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


_DECISION_STATUS_ALIASES = {
    "accepted": DecisionStatus.CONFIRMED.value,
    "provisional": DecisionStatus.PROVISIONALLY_ACCEPTED.value,
    "provisionally accepted": DecisionStatus.PROVISIONALLY_ACCEPTED.value,
}


def normalize_decision_status(value: str | DecisionStatus | None) -> str:
    if value is None:
        return DecisionStatus.PROPOSED.value
    raw = value.value if isinstance(value, DecisionStatus) else str(value)
    key = raw.strip().lower().replace("-", "_")
    if key in _DECISION_STATUS_ALIASES:
        return _DECISION_STATUS_ALIASES[key]
    try:
        return DecisionStatus(key).value
    except ValueError:
        return DecisionStatus.PROPOSED.value


class ReviewProvenance(str, Enum):
    DETERMINISTIC = "deterministic"
    PRIMARY_ONLY = "primary_only"
    TWO_MODEL = "two_model"
    NONE = "none"


class MessageIntent(str, Enum):
    GREETING = "greeting"
    CLARIFICATION = "clarification"
    INITIAL_IDEA = "initial_idea"
    ARCHITECTURE_DECISION = "architecture_decision"
    SCOPE_CHANGE = "scope_change"
    EVIDENCE = "evidence"
    INSISTENCE = "insistence"
    RESOLUTION = "resolution"
    QUESTION = "question"
    GENERAL = "general"


class CriticOutcome(str, Enum):
    AGREE = "agree"
    DISAGREE = "disagree"
    REVISE = "revise"
    ADD_RISK = "add_risk"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SKIPPED = "skipped"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Project state components
# ---------------------------------------------------------------------------


class Assumption(BaseModel):
    id: str = Field(default_factory=lambda: new_id("asm_"))
    statement: str
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    classification: AssumptionClassification = AssumptionClassification.UNVERIFIED
    evidence: str | None = None
    source: str = "user"  # user | grill_mentor | inference — never treat mentor as user approval
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DecisionRevision(BaseModel):
    at: datetime = Field(default_factory=utcnow)
    title: str
    choice: str
    status: str
    rationale: str = ""
    note: str = ""
    actor: str = "system"  # user | system | grill_mentor


class Decision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dec_"))
    title: str
    choice: str
    rationale: str = ""
    alternatives_considered: list[str] = Field(default_factory=list)
    # Prefer DecisionStatus values; legacy "accepted"/"provisional" still load
    status: str = DecisionStatus.CONFIRMED.value
    source: str = "user"  # user | state_patch | grill_mentor | manual_context
    history: list[DecisionRevision] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RejectedApproach(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rej_"))
    approach: str
    reason: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class ConversationSummary(BaseModel):
    """Versioned rolling summary of older conversation turns (non-authoritative)."""

    id: str = Field(default_factory=lambda: new_id("sum_"))
    version: int = 1
    text: str = ""
    covered_through_message_id: str | None = None
    covered_message_count: int = 0
    source: str = "deterministic"  # deterministic | llm | failed_keep_previous
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkingMemory(BaseModel):
    """Ephemeral working set for near-term conversational continuity."""

    current_intent: str | None = None
    active_mode: str | None = None
    unresolved_questions: list[str] = Field(default_factory=list)
    current_task: str = ""
    last_user_correction: str = ""
    # Topics the user explicitly excluded from the current ask (survive compression)
    turn_exclusions: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utcnow)


class Requirement(BaseModel):
    id: str = Field(default_factory=lambda: new_id("req_"))
    text: str
    kind: str = "functional"  # functional | non_functional
    acceptance_criteria: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class Constraint(BaseModel):
    id: str = Field(default_factory=lambda: new_id("con_"))
    text: str
    category: str = "general"  # deadline | skill | resource | tech | other
    created_at: datetime = Field(default_factory=utcnow)


class OpenQuestion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("q_"))
    text: str
    priority: str = "medium"
    answered: bool = False
    answer: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class FindingRevision(BaseModel):
    at: datetime = Field(default_factory=utcnow)
    title: str
    reasoning: str
    severity: Severity
    confidence: float
    note: str = ""


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: new_id("fnd_"))
    title: str
    challenged_claim: str
    reasoning: str
    evidence: list[str] = Field(default_factory=list)
    assumptions_to_verify: list[str] = Field(default_factory=list)
    severity: Severity = Severity.MEDIUM
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    potential_impact: str = ""
    recommended_next_step: str = ""
    provenance: ReviewProvenance = ReviewProvenance.PRIMARY_ONLY
    critic_outcome: CriticOutcome | None = None
    critic_notes: str | None = None
    status: FindingStatus = FindingStatus.OPEN
    invalidation_criteria: str = ""
    history: list[FindingRevision] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
    resolution_note: str | None = None

    def revise(
        self,
        *,
        title: str | None = None,
        reasoning: str | None = None,
        severity: Severity | None = None,
        confidence: float | None = None,
        note: str = "",
    ) -> None:
        self.history.append(
            FindingRevision(
                title=self.title,
                reasoning=self.reasoning,
                severity=self.severity,
                confidence=self.confidence,
                note=note,
            )
        )
        if title is not None:
            self.title = title
        if reasoning is not None:
            self.reasoning = reasoning
        if severity is not None:
            self.severity = severity
        if confidence is not None:
            self.confidence = confidence
        self.updated_at = utcnow()


class Message(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg_"))
    role: str  # user | assistant | system
    content: str
    intent: MessageIntent | None = None
    provenance: ReviewProvenance | None = None
    finding_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class ProjectState(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prj_"))
    name: str
    description: str = ""
    objective: str = ""
    problem_statement: str = ""
    intended_users: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    functional_requirements: list[Requirement] = Field(default_factory=list)
    non_functional_requirements: list[Requirement] = Field(default_factory=list)
    scope_in: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    architecture_notes: str = ""
    architecture_note_history: list[NoteRevision] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    technology_selections: list[TechnologySelection] = Field(default_factory=list)
    data_model_notes: str = ""
    security_notes: str = ""
    testing_notes: str = ""
    note_history: list[NoteRevision] = Field(default_factory=list)
    milestones: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    rejected_approaches: list[RejectedApproach] = Field(default_factory=list)
    implementation_status: str = ""
    completed_milestones: list[str] = Field(default_factory=list)
    outstanding_tasks: list[str] = Field(default_factory=list)
    known_risks: list[str] = Field(default_factory=list)
    behavioural_mode: BehaviouralMode = BehaviouralMode.EXPLORE
    # Long-term conversational memory (summary is non-authoritative vs structured fields)
    conversation_summary: ConversationSummary | None = None
    conversation_summary_history: list[ConversationSummary] = Field(default_factory=list)
    working_memory: WorkingMemory = Field(default_factory=WorkingMemory)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def open_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.status == FindingStatus.OPEN]

    def blocking_findings(self) -> list[Finding]:
        return [
            f
            for f in self.findings
            if f.status == FindingStatus.OPEN
            and f.severity in (Severity.CRITICAL, Severity.HIGH)
        ]

    def accepted_risks(self) -> list[Finding]:
        return [f for f in self.findings if f.status == FindingStatus.ACCEPTED_RISK]

    def touch(self) -> None:
        self.updated_at = utcnow()


# ---------------------------------------------------------------------------
# API / transfer models
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = ""
    initial_message: str | None = None


class ProjectSummary(BaseModel):
    id: str
    name: str
    objective: str
    open_finding_count: int
    message_count: int
    created_at: datetime
    updated_at: datetime


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=16_000)
    behavioural_mode: BehaviouralMode | None = None


class ContextUpdateRequest(BaseModel):
    """User corrections to stored project context (partial update)."""

    name: str | None = None
    description: str | None = None
    objective: str | None = None
    problem_statement: str | None = None
    intended_users: list[str] | None = None
    success_criteria: list[str] | None = None
    scope_in: list[str] | None = None
    scope_out: list[str] | None = None
    tech_stack: list[str] | None = None
    milestones: list[str] | None = None
    preferences: list[str] | None = None
    rejected_approaches: list[dict[str, str]] | None = None
    architecture_notes: str | None = None
    data_model_notes: str | None = None
    security_notes: str | None = None
    testing_notes: str | None = None
    implementation_status: str | None = None
    completed_milestones: list[str] | None = None
    outstanding_tasks: list[str] | None = None
    known_risks: list[str] | None = None


class FindingUpdateRequest(BaseModel):
    status: FindingStatus
    note: str | None = None


class DecisionUpdateRequest(BaseModel):
    """Accept / reject / resolve a decision without silently rewriting its choice."""

    status: DecisionStatus
    note: str | None = None


class ReadinessChecklistItem(BaseModel):
    """One mandatory/conditional readiness check — never trust score alone."""

    id: str
    label: str
    category: str = "mandatory"  # mandatory | conditional | quality
    present: bool = False
    detail: str = ""


class ReadinessResult(BaseModel):
    ready: bool
    status: str  # ready | ready_with_accepted_risks | not_ready
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_essentials: list[str] = Field(default_factory=list)
    accepted_risk_summaries: list[str] = Field(default_factory=list)
    unblock_actions: list[str] = Field(default_factory=list)
    # Extended gate for implementation / agent-prompt generation
    checklist: list[ReadinessChecklistItem] = Field(default_factory=list)
    score_pct: int = 0
    conflicts: list[str] = Field(default_factory=list)
    implementation_ready: bool = False


class SpecificationResult(BaseModel):
    readiness: ReadinessResult
    markdown: str
    structured: dict[str, Any]


class AgentPromptRequest(BaseModel):
    """Optional body for agent-prompt generation."""

    task: str | None = None
    agent: str = "cursor"  # cursor | antigravity | codex
    force: bool = False
    include_skills: bool = True
    user_selected_skills: list[str] = Field(default_factory=list)
    refine_notes: str | None = None


class PromptQualityReport(BaseModel):
    passed: bool = False
    score_pct: int = 0
    issues: list[str] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)


class AgentPromptResult(BaseModel):
    readiness: ReadinessResult
    prompt: str
    blocked: bool = False
    block_reasons: list[str] = Field(default_factory=list)
    structured: dict[str, Any] = Field(default_factory=dict)
    agent: str = "cursor"
    skills_used: list[dict[str, Any]] = Field(default_factory=list)
    skill_reasons: dict[str, str] = Field(default_factory=dict)
    quality: PromptQualityReport | None = None
    warnings: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    message: Message
    findings: list[Finding]
    project: ProjectState
    readiness: ReadinessResult
    review_limitations: list[str] = Field(default_factory=list)
    provider_status: str | None = None
    provider_used: str | None = None
    offline_review: bool = False
    funding_source: str | None = None
    free_tier: Any | None = None
    behavioural_mode: BehaviouralMode = BehaviouralMode.EXPLORE
