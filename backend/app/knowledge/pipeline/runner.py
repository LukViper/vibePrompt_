"""Book processing pipeline orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.knowledge.acquisition.licensing import evaluate_rights
from app.knowledge.models import BookStatus, ProcessingJob, utcnow
from app.knowledge.pipeline.clean import clean_text
from app.knowledge.pipeline.extract_concepts import extract_concepts_from_chapters
from app.knowledge.pipeline.extract_text import extract_text
from app.knowledge.pipeline.segment import segment_chapters
from app.knowledge.store import KnowledgeStore


class PipelineError(Exception):
    def __init__(self, message: str, stage: str) -> None:
        super().__init__(message)
        self.message = message
        self.stage = stage


def process_book(store: KnowledgeStore, book_id: str, *, actor: str | None = None) -> ProcessingJob:
    book = store.get_book(book_id)
    if book is None:
        raise PipelineError("Book not found", "lookup")

    decision = evaluate_rights(
        usage_permission=book.usage_permission,
        rights_confirmed=book.rights_confirmed,
    )
    if not decision.allowed:
        raise PipelineError(decision.reason, "licensing")

    if not book.source_path or not Path(book.source_path).is_file():
        raise PipelineError("No source file on disk", "file")

    job = ProcessingJob(book_id=book_id, status="running", stage="validating", started_at=utcnow())
    job.log.append("Pipeline started")
    store.create_job(job)

    report: dict[str, Any] = {"stages": []}

    def _set_stage(stage: str, detail: str = "") -> None:
        nonlocal book
        job.stage = stage
        job.log.append(f"{stage}: {detail}" if detail else stage)
        status_map = {
            "validating": BookStatus.VALIDATING,
            "extracting": BookStatus.EXTRACTING,
            "cleaning": BookStatus.CLEANING,
            "segmenting": BookStatus.SEGMENTING,
            "extracting_concepts": BookStatus.EXTRACTING_CONCEPTS,
        }
        if stage in status_map:
            book.status = status_map[stage]
            book.status_detail = detail or stage
            store.update_book(book)
        store.update_job(job)

    try:
        _set_stage("validating", Path(book.source_path).name)
        path = Path(book.source_path)
        if path.stat().st_size <= 0:
            raise PipelineError("Empty file", "validating")
        report["stages"].append({"stage": "validating", "ok": True})

        _set_stage("extracting")
        extraction = extract_text(path, book.mime_type)
        if extraction.warnings:
            job.log.extend(f"warn: {w}" for w in extraction.warnings)
        if not extraction.text.strip():
            raise PipelineError("No text extracted", "extracting")
        report["stages"].append(
            {
                "stage": "extracting",
                "ok": True,
                "method": extraction.method,
                "chars": len(extraction.text),
                "pages": len(extraction.pages),
                "warnings": extraction.warnings,
            }
        )

        _set_stage("cleaning")
        cleaned = clean_text(extraction.text)
        report["stages"].append({"stage": "cleaning", "ok": True, "chars": len(cleaned)})

        _set_stage("segmenting")
        chapters = segment_chapters(cleaned, extraction.pages)
        store.replace_chapters(book_id, chapters)
        book.chapter_count = len(chapters)
        store.update_book(book)
        report["stages"].append(
            {"stage": "segmenting", "ok": True, "chapters": len(chapters)}
        )

        _set_stage("extracting_concepts")
        concepts = extract_concepts_from_chapters(
            book_id=book_id,
            chapters=chapters,
            target_skill=book.target_skill,
        )
        store.replace_concepts(book_id, concepts)
        book.concept_count = len(concepts)
        book.status = BookStatus.READY
        book.status_detail = f"Ready — {len(concepts)} concepts from {len(chapters)} chapters"
        book.extracted_at = utcnow()
        store.update_book(book)
        report["stages"].append(
            {"stage": "extracting_concepts", "ok": True, "concepts": len(concepts)}
        )
        report["skill_mapping"] = {
            "target_skill": book.target_skill,
            "associated_skill_ids": book.associated_skill_ids,
        }

        job.status = "succeeded"
        job.stage = "ready"
        job.finished_at = utcnow()
        job.report = report
        job.log.append("Pipeline completed")
        store.update_job(job)
        store.audit(
            "process_book",
            actor=actor,
            entity_type="book",
            entity_id=book_id,
            detail={"concepts": len(concepts), "chapters": len(chapters)},
        )
        return job
    except Exception as exc:  # noqa: BLE001 — surface as job failure
        stage = getattr(exc, "stage", job.stage)
        job.status = "failed"
        job.stage = stage
        job.error = str(getattr(exc, "message", exc))
        job.finished_at = utcnow()
        job.log.append(f"FAILED at {stage}: {job.error}")
        job.report = {**report, "error": job.error, "failed_stage": stage}
        store.update_job(job)
        book.status = BookStatus.FAILED
        book.status_detail = job.error or "Processing failed"
        store.update_book(book)
        store.audit(
            "process_book_failed",
            actor=actor,
            entity_type="book",
            entity_id=book_id,
            detail={"error": job.error, "stage": stage},
        )
        return job
