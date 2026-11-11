"""Knowledge Library book, concept, and job models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "bk_") -> str:
    return f"{prefix}{uuid4().hex[:12]}"


class BookStatus(str, Enum):
    DISCOVERED = "discovered"
    AWAITING_FILE = "awaiting_file"
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    EXTRACTING = "extracting"
    CLEANING = "cleaning"
    SEGMENTING = "segmenting"
    EXTRACTING_CONCEPTS = "extracting_concepts"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class KnowledgeKind(str, Enum):
    CONCEPT = "concept"
    FRAMEWORK = "framework"
    METHODOLOGY = "methodology"
    PRINCIPLE = "principle"
    TECHNIQUE = "technique"
    QUESTION_PATTERN = "question_pattern"
    EXAMPLE = "example"
    LIMITATION = "limitation"
    APPLICATION = "application"
    DECISION_RULE = "decision_rule"


class BookCreate(BaseModel):
    title: str
    author: str = "Unknown"
    category: str = "general"
    description: str = ""
    copyright_note: str = ""
    usage_permission: str = "unknown"
    topics: list[str] = Field(default_factory=list)
    catalog_slug: str | None = None
    target_skill: str | None = None
    isbn: str | None = None
    publisher: str | None = None
    year: int | None = None


class BookUpdate(BaseModel):
    title: str | None = None
    author: str | None = None
    category: str | None = None
    description: str | None = None
    copyright_note: str | None = None
    usage_permission: str | None = None
    topics: list[str] | None = None
    enabled: bool | None = None
    target_skill: str | None = None


class BookRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    catalog_slug: str | None = None
    title: str
    author: str = "Unknown"
    category: str = "general"
    description: str = ""
    topics: list[str] = Field(default_factory=list)
    isbn: str | None = None
    publisher: str | None = None
    year: int | None = None
    target_skill: str | None = None
    source_filename: str | None = None
    source_path: str | None = None
    mime_type: str | None = None
    size_bytes: int = 0
    sha256: str | None = None
    source_url: str | None = None
    status: BookStatus = BookStatus.AWAITING_FILE
    status_detail: str = ""
    copyright_note: str = ""
    usage_permission: str = "unknown"
    rights_confirmed: bool = False
    enabled: bool = True
    associated_skill_ids: list[str] = Field(default_factory=list)
    chapter_count: int = 0
    concept_count: int = 0
    extracted_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    created_by: str | None = None


class ChapterSegment(BaseModel):
    index: int
    title: str
    text: str
    char_start: int = 0
    char_end: int = 0
    page_start: int | None = None
    page_end: int | None = None


class KnowledgeConcept(BaseModel):
    id: str = Field(default_factory=lambda: new_id("kc_"))
    book_id: str
    kind: KnowledgeKind
    title: str
    summary: str
    application: str = ""
    chapter_ref: str | None = None
    target_skill: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class ProcessingJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("job_"))
    book_id: str
    status: str = "queued"
    stage: str = "queued"
    log: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report: dict[str, Any] = Field(default_factory=dict)


class BookPreview(BaseModel):
    book: BookRecord
    text_preview: str
    chapters: list[dict[str, Any]]
    concepts: list[KnowledgeConcept]
    latest_job: ProcessingJob | None = None


class AssociateSkillsRequest(BaseModel):
    skill_ids: list[str]


class UploadRightsForm(BaseModel):
    usage_permission: str = "owned"
    rights_confirmed: bool = False
    confirmation_text: str = ""
    catalog_slug: str | None = None
    title: str | None = None
    author: str | None = None
    target_skill: str | None = None
    category: str | None = None
    description: str = ""
    copyright_note: str = ""
