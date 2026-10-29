"""Domain models for project state, findings, and conversation."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


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
    evidence: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Decision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dec_"))
    title: str
    choice: str
    rationale: str = ""
    alternatives_considered: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
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
    objective: str = ""
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
    tech_stack: list[str] = Field(default_factory=list)
    data_model_notes: str = ""
    security_notes: str = ""
    testing_notes: str = ""
    milestones: list[str] = Field(default_factory=list)
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


class FindingUpdateRequest(BaseModel):
    status: FindingStatus
    note: str | None = None


class ReadinessResult(BaseModel):
    ready: bool
    status: str  # ready | ready_with_accepted_risks | not_ready
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_essentials: list[str] = Field(default_factory=list)
    accepted_risk_summaries: list[str] = Field(default_factory=list)
    unblock_actions: list[str] = Field(default_factory=list)


class SpecificationResult(BaseModel):
    readiness: ReadinessResult
    markdown: str
    structured: dict[str, Any]


class ChatResponse(BaseModel):
    message: Message
    findings: list[Finding]
    project: ProjectState
    readiness: ReadinessResult
    review_limitations: list[str] = Field(default_factory=list)
    provider_status: str | None = None
    provider_used: str | None = None
    offline_review: bool = False
