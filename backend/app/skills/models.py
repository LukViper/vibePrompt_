"""Modular skill package models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "skl_") -> str:
    return f"{prefix}{uuid4().hex[:12]}"


class SkillStatus(str, Enum):
    BUILTIN = "builtin"
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class SkillModeBinding(str, Enum):
    """Maps skills onto conversational modes (primary filter for retrieval)."""

    CONVERSATIONAL = "conversational"
    BRAINSTORMING = "brainstorming"
    GRILL_REVIEW = "grill_review"
    # Capability skills retrieved when slug is active / linked
    ARCHITECTURE = "architecture"
    PROMPT_ENGINEERING = "prompt_engineering"
    PROJECT_PLANNING = "project_planning"


class SkillPrinciple(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pr_"))
    title: str
    summary: str
    application: str = ""
    when_to_use: str = ""
    when_not_to_use: str = ""
    source_book_id: str | None = None
    chapter_ref: str | None = None
    original_concept: str | None = None
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)


class SkillPackage(BaseModel):
    id: str = Field(default_factory=new_id)
    slug: str
    name: str
    description: str = ""
    status: SkillStatus = SkillStatus.DRAFT
    mode_binding: SkillModeBinding | None = None
    version: int = 1
    principles: list[SkillPrinciple] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    question_patterns: list[str] = Field(default_factory=list)
    decision_rules: list[str] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    evaluation_cases: list[dict[str, Any]] = Field(default_factory=list)
    source_book_ids: list[str] = Field(default_factory=list)
    parent_skill_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    approved_at: datetime | None = None
    approved_by: str | None = None


class SkillSummary(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    status: SkillStatus
    mode_binding: SkillModeBinding | None
    version: int
    source_book_count: int
    updated_at: datetime


class SkillDraftRequest(BaseModel):
    book_ids: list[str] = Field(default_factory=list)
    book_id: str | None = None  # convenience single-book
    target_skill_id: str | None = None
    target_slug: str | None = None
    name: str | None = None
    mode_binding: SkillModeBinding | None = None


class SkillApproveRequest(BaseModel):
    note: str | None = None


class SkillRollbackRequest(BaseModel):
    version: int
    note: str | None = None
