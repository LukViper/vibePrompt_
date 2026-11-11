"""SQLite persistence for Knowledge Library and skill packages."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.knowledge.models import (
    BookRecord,
    BookStatus,
    KnowledgeConcept,
    KnowledgeKind,
    ProcessingJob,
    new_id,
    utcnow,
)
from app.persistence.schema import apply_schema
from app.skills.models import SkillPackage, SkillStatus, SkillSummary


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class KnowledgeStore:
    def __init__(self, database_path: str, *, skills_root: str | Path | None = None) -> None:
        self.database_path = database_path
        self.skills_root = Path(skills_root or Path(database_path).parent / "skills")
        self.skills_root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                apply_schema(conn)
                for stmt in KNOWLEDGE_SCHEMA:
                    conn.execute(stmt)
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------ books
    def create_book(self, book: BookRecord) -> BookRecord:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO knowledge_books (
                        id, catalog_slug, title, author, category, description, topics_json,
                        isbn, publisher, year, target_skill, source_filename, source_path,
                        mime_type, size_bytes, sha256, source_url, status, status_detail,
                        copyright_note, usage_permission, rights_confirmed, enabled,
                        associated_skill_ids_json, chapter_count, concept_count,
                        extracted_at, created_at, updated_at, created_by
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        book.id,
                        book.catalog_slug,
                        book.title,
                        book.author,
                        book.category,
                        book.description,
                        json.dumps(book.topics),
                        book.isbn,
                        book.publisher,
                        book.year,
                        book.target_skill,
                        book.source_filename,
                        book.source_path,
                        book.mime_type,
                        book.size_bytes,
                        book.sha256,
                        book.source_url,
                        book.status.value,
                        book.status_detail,
                        book.copyright_note,
                        book.usage_permission,
                        1 if book.rights_confirmed else 0,
                        1 if book.enabled else 0,
                        json.dumps(book.associated_skill_ids),
                        book.chapter_count,
                        book.concept_count,
                        _iso(book.extracted_at),
                        _iso(book.created_at),
                        _iso(book.updated_at),
                        book.created_by,
                    ),
                )
                conn.commit()
                return book
            finally:
                conn.close()

    def update_book(self, book: BookRecord) -> BookRecord:
        book.updated_at = utcnow()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE knowledge_books SET
                        catalog_slug=?, title=?, author=?, category=?, description=?,
                        topics_json=?, isbn=?, publisher=?, year=?, target_skill=?,
                        source_filename=?, source_path=?, mime_type=?, size_bytes=?,
                        sha256=?, source_url=?, status=?, status_detail=?,
                        copyright_note=?, usage_permission=?, rights_confirmed=?,
                        enabled=?, associated_skill_ids_json=?, chapter_count=?,
                        concept_count=?, extracted_at=?, updated_at=?, created_by=?
                    WHERE id=?
                    """,
                    (
                        book.catalog_slug,
                        book.title,
                        book.author,
                        book.category,
                        book.description,
                        json.dumps(book.topics),
                        book.isbn,
                        book.publisher,
                        book.year,
                        book.target_skill,
                        book.source_filename,
                        book.source_path,
                        book.mime_type,
                        book.size_bytes,
                        book.sha256,
                        book.source_url,
                        book.status.value,
                        book.status_detail,
                        book.copyright_note,
                        book.usage_permission,
                        1 if book.rights_confirmed else 0,
                        1 if book.enabled else 0,
                        json.dumps(book.associated_skill_ids),
                        book.chapter_count,
                        book.concept_count,
                        _iso(book.extracted_at),
                        _iso(book.updated_at),
                        book.created_by,
                        book.id,
                    ),
                )
                conn.commit()
                return book
            finally:
                conn.close()

    def get_book(self, book_id: str) -> BookRecord | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM knowledge_books WHERE id=?", (book_id,)
                ).fetchone()
                return _row_to_book(row) if row else None
            finally:
                conn.close()

    def find_by_sha256(self, sha256: str) -> BookRecord | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM knowledge_books WHERE sha256=? AND status != ?",
                    (sha256, BookStatus.ARCHIVED.value),
                ).fetchone()
                return _row_to_book(row) if row else None
            finally:
                conn.close()

    def list_books(
        self,
        *,
        skill: str | None = None,
        status: str | None = None,
        q: str | None = None,
        include_archived: bool = False,
    ) -> list[BookRecord]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM knowledge_books ORDER BY updated_at DESC"
                ).fetchall()
                books = [_row_to_book(r) for r in rows]
            finally:
                conn.close()
        if not include_archived:
            books = [b for b in books if b.status != BookStatus.ARCHIVED]
        if skill:
            books = [
                b
                for b in books
                if b.target_skill == skill or skill in b.associated_skill_ids
            ]
        if status:
            books = [b for b in books if b.status.value == status]
        if q:
            needle = q.lower()
            books = [
                b
                for b in books
                if needle in b.title.lower()
                or needle in b.author.lower()
                or needle in (b.catalog_slug or "")
            ]
        return books

    def archive_book(self, book_id: str) -> BookRecord | None:
        book = self.get_book(book_id)
        if not book:
            return None
        book.status = BookStatus.ARCHIVED
        book.status_detail = "Archived by administrator"
        book.enabled = False
        return self.update_book(book)

    # -------------------------------------------------------------- chapters
    def replace_chapters(self, book_id: str, chapters: list[dict[str, Any]]) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM book_chapters WHERE book_id=?", (book_id,))
                for ch in chapters:
                    conn.execute(
                        """
                        INSERT INTO book_chapters (
                            id, book_id, idx, title, text, char_start, char_end,
                            page_start, page_end
                        ) VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            new_id("ch_"),
                            book_id,
                            ch["index"],
                            ch["title"],
                            ch["text"],
                            ch.get("char_start", 0),
                            ch.get("char_end", 0),
                            ch.get("page_start"),
                            ch.get("page_end"),
                        ),
                    )
                conn.commit()
            finally:
                conn.close()

    def list_chapters(self, book_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM book_chapters WHERE book_id=? ORDER BY idx",
                    (book_id,),
                ).fetchall()
                return [
                    {
                        "index": r["idx"],
                        "title": r["title"],
                        "text": r["text"],
                        "char_start": r["char_start"],
                        "char_end": r["char_end"],
                        "page_start": r["page_start"],
                        "page_end": r["page_end"],
                        "preview": (r["text"] or "")[:400],
                    }
                    for r in rows
                ]
            finally:
                conn.close()

    def get_text_preview(self, book_id: str, limit: int = 2000) -> str:
        chapters = self.list_chapters(book_id)
        blob = "\n\n".join(f"# {c['title']}\n{c['text']}" for c in chapters)
        return blob[:limit]

    # -------------------------------------------------------------- concepts
    def replace_concepts(self, book_id: str, concepts: list[KnowledgeConcept]) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM extracted_concepts WHERE book_id=?", (book_id,))
                for c in concepts:
                    conn.execute(
                        """
                        INSERT INTO extracted_concepts (
                            id, book_id, kind, title, summary, application,
                            chapter_ref, target_skill, confidence, tags_json,
                            metadata_json, created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            c.id,
                            c.book_id,
                            c.kind.value,
                            c.title,
                            c.summary,
                            c.application,
                            c.chapter_ref,
                            c.target_skill,
                            c.confidence,
                            json.dumps(c.tags),
                            json.dumps(c.metadata),
                            _iso(c.created_at),
                        ),
                    )
                conn.commit()
            finally:
                conn.close()

    def list_concepts(
        self,
        book_id: str | None = None,
        *,
        target_skill: str | None = None,
        enabled_books_only: bool = False,
    ) -> list[KnowledgeConcept]:
        with self._lock:
            conn = self._connect()
            try:
                sql = "SELECT c.* FROM extracted_concepts c"
                params: list[Any] = []
                where: list[str] = []
                if enabled_books_only:
                    sql += " JOIN knowledge_books b ON b.id = c.book_id"
                    where.append("b.enabled = 1")
                    where.append("b.status = ?")
                    params.append(BookStatus.READY.value)
                if book_id:
                    where.append("c.book_id = ?")
                    params.append(book_id)
                if target_skill:
                    where.append("(c.target_skill = ? OR c.target_skill IS NULL)")
                    params.append(target_skill)
                if where:
                    sql += " WHERE " + " AND ".join(where)
                sql += " ORDER BY c.confidence DESC, c.created_at DESC"
                rows = conn.execute(sql, params).fetchall()
                return [_row_to_concept(r) for r in rows]
            finally:
                conn.close()

    def update_concept(self, concept: KnowledgeConcept) -> KnowledgeConcept:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE extracted_concepts SET
                        kind=?, title=?, summary=?, application=?, chapter_ref=?,
                        target_skill=?, confidence=?, tags_json=?, metadata_json=?
                    WHERE id=?
                    """,
                    (
                        concept.kind.value,
                        concept.title,
                        concept.summary,
                        concept.application,
                        concept.chapter_ref,
                        concept.target_skill,
                        concept.confidence,
                        json.dumps(concept.tags),
                        json.dumps(concept.metadata),
                        concept.id,
                    ),
                )
                conn.commit()
                return concept
            finally:
                conn.close()

    # ------------------------------------------------------------------ jobs
    def create_job(self, job: ProcessingJob) -> ProcessingJob:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO book_processing_jobs (
                        id, book_id, status, stage, log_json, error,
                        started_at, finished_at, report_json
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        job.id,
                        job.book_id,
                        job.status,
                        job.stage,
                        json.dumps(job.log),
                        job.error,
                        _iso(job.started_at),
                        _iso(job.finished_at),
                        json.dumps(job.report),
                    ),
                )
                conn.commit()
                return job
            finally:
                conn.close()

    def update_job(self, job: ProcessingJob) -> ProcessingJob:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE book_processing_jobs SET
                        status=?, stage=?, log_json=?, error=?,
                        started_at=?, finished_at=?, report_json=?
                    WHERE id=?
                    """,
                    (
                        job.status,
                        job.stage,
                        json.dumps(job.log),
                        job.error,
                        _iso(job.started_at),
                        _iso(job.finished_at),
                        json.dumps(job.report),
                        job.id,
                    ),
                )
                conn.commit()
                return job
            finally:
                conn.close()

    def latest_job(self, book_id: str) -> ProcessingJob | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT * FROM book_processing_jobs
                    WHERE book_id=? ORDER BY rowid DESC LIMIT 1
                    """,
                    (book_id,),
                ).fetchone()
                return _row_to_job(row) if row else None
            finally:
                conn.close()

    # ----------------------------------------------------------------- audit
    def audit(
        self,
        action: str,
        *,
        actor: str | None,
        entity_type: str,
        entity_id: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO acquisition_logs (
                        id, action, actor, entity_type, entity_id, detail_json, created_at
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        new_id("log_"),
                        action,
                        actor,
                        entity_type,
                        entity_id,
                        json.dumps(detail or {}),
                        _iso(utcnow()),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM acquisition_logs
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ---------------------------------------------------------------- skills
    def upsert_skill(self, skill: SkillPackage) -> SkillPackage:
        skill.updated_at = utcnow()
        payload = skill.model_dump(mode="json")
        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    "SELECT id FROM skill_registry WHERE id=?", (skill.id,)
                ).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE skill_registry SET
                            slug=?, name=?, description=?, status=?, mode_binding=?,
                            version=?, parent_skill_id=?, package_json=?,
                            approved_at=?, approved_by=?, updated_at=?
                        WHERE id=?
                        """,
                        (
                            skill.slug,
                            skill.name,
                            skill.description,
                            skill.status.value,
                            skill.mode_binding.value if skill.mode_binding else None,
                            skill.version,
                            skill.parent_skill_id,
                            json.dumps(payload),
                            _iso(skill.approved_at),
                            skill.approved_by,
                            _iso(skill.updated_at),
                            skill.id,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO skill_registry (
                            id, slug, name, description, status, mode_binding,
                            version, parent_skill_id, package_json,
                            approved_at, approved_by, created_at, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            skill.id,
                            skill.slug,
                            skill.name,
                            skill.description,
                            skill.status.value,
                            skill.mode_binding.value if skill.mode_binding else None,
                            skill.version,
                            skill.parent_skill_id,
                            json.dumps(payload),
                            _iso(skill.approved_at),
                            skill.approved_by,
                            _iso(skill.created_at),
                            _iso(skill.updated_at),
                        ),
                    )
                conn.execute(
                    """
                    INSERT INTO skill_versions (
                        id, skill_id, version, status, package_json, created_at, note
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        new_id("sv_"),
                        skill.id,
                        skill.version,
                        skill.status.value,
                        json.dumps(payload),
                        _iso(utcnow()),
                        None,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        self._write_skill_files(skill)
        return skill

    def get_skill(self, skill_id: str) -> SkillPackage | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT package_json FROM skill_registry WHERE id=?", (skill_id,)
                ).fetchone()
                if not row:
                    return None
                return SkillPackage.model_validate(json.loads(row["package_json"]))
            finally:
                conn.close()

    def get_skill_by_slug(self, slug: str) -> SkillPackage | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT package_json FROM skill_registry
                    WHERE slug=? AND status IN ('active','builtin')
                    ORDER BY version DESC LIMIT 1
                    """,
                    (slug,),
                ).fetchone()
                if not row:
                    # fall back to any status
                    row = conn.execute(
                        "SELECT package_json FROM skill_registry WHERE slug=? ORDER BY version DESC LIMIT 1",
                        (slug,),
                    ).fetchone()
                if not row:
                    return None
                return SkillPackage.model_validate(json.loads(row["package_json"]))
            finally:
                conn.close()

    def list_skills(self) -> list[SkillSummary]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT package_json FROM skill_registry ORDER BY updated_at DESC"
                ).fetchall()
            finally:
                conn.close()
        out: list[SkillSummary] = []
        for row in rows:
            pkg = SkillPackage.model_validate(json.loads(row["package_json"]))
            out.append(
                SkillSummary(
                    id=pkg.id,
                    slug=pkg.slug,
                    name=pkg.name,
                    description=pkg.description,
                    status=pkg.status,
                    mode_binding=pkg.mode_binding,
                    version=pkg.version,
                    source_book_count=len(pkg.source_book_ids),
                    updated_at=pkg.updated_at,
                )
            )
        return out

    def list_skill_versions(self, skill_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT id, skill_id, version, status, created_at, note
                    FROM skill_versions WHERE skill_id=? ORDER BY version DESC
                    """,
                    (skill_id,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_skill_version(self, skill_id: str, version: int) -> SkillPackage | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT package_json FROM skill_versions
                    WHERE skill_id=? AND version=?
                    """,
                    (skill_id, version),
                ).fetchone()
                if not row:
                    return None
                return SkillPackage.model_validate(json.loads(row["package_json"]))
            finally:
                conn.close()

    def save_evaluation(self, record: dict[str, Any]) -> dict[str, Any]:
        rid = record.get("id") or new_id("ev_")
        record = {**record, "id": rid}
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO skill_evaluations (
                        id, skill_id, version, baseline_skill_id, metrics_json,
                        passed, notes, created_at
                    ) VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        rid,
                        record["skill_id"],
                        record.get("version"),
                        record.get("baseline_skill_id"),
                        json.dumps(record.get("metrics") or {}),
                        1 if record.get("passed") else 0,
                        record.get("notes"),
                        _iso(utcnow()),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return record

    def _write_skill_files(self, skill: SkillPackage) -> None:
        root = self.skills_root / skill.slug / f"v{skill.version}"
        root.mkdir(parents=True, exist_ok=True)
        (root / "evaluation").mkdir(exist_ok=True)
        (root / "chapters").mkdir(exist_ok=True)

        when = skill.mode_binding.value if skill.mode_binding else "on-demand"
        skill_md = [
            f"# {skill.name}",
            "",
            f"**Purpose:** {skill.description}",
            "",
            f"**Status:** {skill.status.value}  ",
            f"**Version:** {skill.version}  ",
            f"**Primary mode binding:** {when}",
            "",
            "## When to activate",
            f"- When the conversation needs `{skill.slug}` behaviours.",
            "",
            "## When not to activate",
            "- When the user request is outside this skill's domain.",
            "- When a higher-priority orchestrated skill already covers the turn.",
            "",
            "## Core operating principles",
        ]
        for p in skill.principles[:12]:
            skill_md.append(f"- **{p.title}:** {p.summary}")
        skill_md.extend(
            [
                "",
                "## Execution workflow",
                "1. Read user goal and project context.",
                "2. Apply decision rules below.",
                "3. Ask at most one high-value question if needed.",
                "4. Produce structured, actionable output.",
                "",
                "## Supporting files",
                "- `principles.md`, `decision_rules.md`, `patterns.md`, `glossary.md`,",
                "  `cheatsheet.md`, `examples.md`, `anti_patterns.md`, `sources.json`",
                "",
                "_Do not reproduce copyrighted passages. Use abstractions only._",
                "",
            ]
        )
        (root / "SKILL.md").write_text("\n".join(skill_md), encoding="utf-8")
        (root / "skill.md").write_text("\n".join(skill_md), encoding="utf-8")

        principles_md = ["# Principles\n"]
        for p in skill.principles:
            principles_md.append(
                f"## {p.title}\n\n{p.summary}\n\n"
                f"**Application:** {p.application}\n\n"
                f"- When: {p.when_to_use or 'n/a'}\n"
                f"- When not: {p.when_not_to_use or 'n/a'}\n"
                f"- Source book: {p.source_book_id or 'n/a'}\n"
                f"- Chapter: {p.chapter_ref or 'n/a'}\n"
                f"- Confidence: {p.confidence}\n"
            )
        (root / "principles.md").write_text("\n".join(principles_md), encoding="utf-8")
        frameworks_md = "# Frameworks\n\n" + "\n".join(f"- {f}" for f in skill.frameworks)
        (root / "frameworks.md").write_text(frameworks_md, encoding="utf-8")

        decision_md = "# Decision rules\n\n" + "\n".join(
            f"- {r}" for r in skill.decision_rules
        )
        (root / "decision_rules.md").write_text(decision_md, encoding="utf-8")
        (root / "decision_rules.json").write_text(
            json.dumps(skill.decision_rules, indent=2), encoding="utf-8"
        )

        patterns = skill.question_patterns or []
        (root / "patterns.md").write_text(
            "# Patterns\n\n" + "\n".join(f"- {q}" for q in patterns),
            encoding="utf-8",
        )
        (root / "question_patterns.json").write_text(
            json.dumps(patterns, indent=2), encoding="utf-8"
        )
        glossary_lines = ["# Glossary\n", "Independently authored terms for this skill.\n"]
        for p in skill.principles[:20]:
            glossary_lines.append(f"- **{p.title}:** {p.summary[:160]}")
        (root / "glossary.md").write_text("\n".join(glossary_lines), encoding="utf-8")
        (root / "cheatsheet.md").write_text(
            "# Cheatsheet\n\n"
            + "\n".join(f"1. {p.title} — {p.summary[:120]}" for p in skill.principles[:10]),
            encoding="utf-8",
        )
        (root / "conversation_strategy.md").write_text(
            "# Conversation strategy\n\n"
            f"Activate `{skill.slug}` when relevant. Prefer one clarifying question. "
            "Reuse prior answers. Defer to the orchestrator when skills conflict.\n",
            encoding="utf-8",
        )
        (root / "examples.md").write_text(
            "# Examples\n\n```json\n"
            + json.dumps(skill.examples, indent=2)
            + "\n```\n",
            encoding="utf-8",
        )
        (root / "examples.json").write_text(
            json.dumps(skill.examples, indent=2), encoding="utf-8"
        )
        (root / "anti_patterns.md").write_text(
            "# Anti-patterns\n\n"
            "- Repeating questions already answered.\n"
            "- Loading entire source books into context.\n"
            "- Quoting substantial copyrighted passages.\n"
            "- Criticizing without a concrete improvement path.\n"
            "- Treating longer answers as higher quality.\n",
            encoding="utf-8",
        )
        (root / "metadata.json").write_text(
            json.dumps(
                {
                    "slug": skill.slug,
                    "name": skill.name,
                    "version": skill.version,
                    "status": skill.status.value,
                    "mode_binding": skill.mode_binding.value if skill.mode_binding else None,
                    "source_book_ids": skill.source_book_ids,
                    "parent_skill_id": skill.parent_skill_id,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (root / "evaluation" / "test_cases.json").write_text(
            json.dumps(skill.evaluation_cases, indent=2), encoding="utf-8"
        )
        (root / "evaluation" / "evaluation_results.json").write_text(
            json.dumps({"status": "pending_human_or_automated_run"}, indent=2),
            encoding="utf-8",
        )
        (root / "evaluation_cases.json").write_text(
            json.dumps(skill.evaluation_cases, indent=2), encoding="utf-8"
        )
        (root / "sources.json").write_text(
            json.dumps(
                {
                    "source_book_ids": skill.source_book_ids,
                    "parent_skill_id": skill.parent_skill_id,
                    "note": "Summaries are independently authored abstractions, not quotations.",
                    "attribution": "Package layout inspired by MIT book-to-skill (virgiliojr94).",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        # Placeholder so chapters/ exists; real chapter abstracts written during LLM synthesis
        (root / "chapters" / "README.md").write_text(
            "# Chapter abstracts\n\n"
            "Store independently written chapter-level abstracts here — never verbatim book text.\n",
            encoding="utf-8",
        )


def _row_to_book(row: sqlite3.Row) -> BookRecord:
    return BookRecord(
        id=row["id"],
        catalog_slug=row["catalog_slug"],
        title=row["title"],
        author=row["author"],
        category=row["category"],
        description=row["description"] or "",
        topics=json.loads(row["topics_json"] or "[]"),
        isbn=row["isbn"],
        publisher=row["publisher"],
        year=row["year"],
        target_skill=row["target_skill"],
        source_filename=row["source_filename"],
        source_path=row["source_path"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"] or 0,
        sha256=row["sha256"],
        source_url=row["source_url"],
        status=BookStatus(row["status"]),
        status_detail=row["status_detail"] or "",
        copyright_note=row["copyright_note"] or "",
        usage_permission=row["usage_permission"] or "unknown",
        rights_confirmed=bool(row["rights_confirmed"]),
        enabled=bool(row["enabled"]),
        associated_skill_ids=json.loads(row["associated_skill_ids_json"] or "[]"),
        chapter_count=row["chapter_count"] or 0,
        concept_count=row["concept_count"] or 0,
        extracted_at=_parse_dt(row["extracted_at"]),
        created_at=_parse_dt(row["created_at"]) or utcnow(),
        updated_at=_parse_dt(row["updated_at"]) or utcnow(),
        created_by=row["created_by"],
    )


def _row_to_concept(row: sqlite3.Row) -> KnowledgeConcept:
    return KnowledgeConcept(
        id=row["id"],
        book_id=row["book_id"],
        kind=KnowledgeKind(row["kind"]),
        title=row["title"],
        summary=row["summary"],
        application=row["application"] or "",
        chapter_ref=row["chapter_ref"],
        target_skill=row["target_skill"],
        confidence=row["confidence"] or 0.5,
        tags=json.loads(row["tags_json"] or "[]"),
        metadata=json.loads(row["metadata_json"] or "{}"),
        created_at=_parse_dt(row["created_at"]) or utcnow(),
    )


def _row_to_job(row: sqlite3.Row) -> ProcessingJob:
    return ProcessingJob(
        id=row["id"],
        book_id=row["book_id"],
        status=row["status"],
        stage=row["stage"],
        log=json.loads(row["log_json"] or "[]"),
        error=row["error"],
        started_at=_parse_dt(row["started_at"]),
        finished_at=_parse_dt(row["finished_at"]),
        report=json.loads(row["report_json"] or "{}"),
    )


KNOWLEDGE_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS knowledge_books (
        id TEXT PRIMARY KEY,
        catalog_slug TEXT,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        category TEXT,
        description TEXT,
        topics_json TEXT,
        isbn TEXT,
        publisher TEXT,
        year INTEGER,
        target_skill TEXT,
        source_filename TEXT,
        source_path TEXT,
        mime_type TEXT,
        size_bytes INTEGER DEFAULT 0,
        sha256 TEXT,
        source_url TEXT,
        status TEXT NOT NULL,
        status_detail TEXT,
        copyright_note TEXT,
        usage_permission TEXT,
        rights_confirmed INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        associated_skill_ids_json TEXT,
        chapter_count INTEGER DEFAULT 0,
        concept_count INTEGER DEFAULT 0,
        extracted_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        created_by TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_knowledge_books_status
    ON knowledge_books(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_knowledge_books_sha
    ON knowledge_books(sha256)
    """,
    """
    CREATE TABLE IF NOT EXISTS book_sources (
        id TEXT PRIMARY KEY,
        book_id TEXT,
        catalog_slug TEXT,
        kind TEXT,
        label TEXT,
        url TEXT,
        valid INTEGER,
        detail_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(book_id) REFERENCES knowledge_books(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS book_files (
        id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL,
        path TEXT NOT NULL,
        filename TEXT,
        mime_type TEXT,
        size_bytes INTEGER,
        sha256 TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(book_id) REFERENCES knowledge_books(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS book_chapters (
        id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL,
        idx INTEGER NOT NULL,
        title TEXT,
        text TEXT,
        char_start INTEGER,
        char_end INTEGER,
        page_start INTEGER,
        page_end INTEGER,
        FOREIGN KEY(book_id) REFERENCES knowledge_books(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS book_processing_jobs (
        id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL,
        status TEXT NOT NULL,
        stage TEXT,
        log_json TEXT,
        error TEXT,
        started_at TEXT,
        finished_at TEXT,
        report_json TEXT,
        FOREIGN KEY(book_id) REFERENCES knowledge_books(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS extracted_concepts (
        id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        application TEXT,
        chapter_ref TEXT,
        target_skill TEXT,
        confidence REAL,
        tags_json TEXT,
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(book_id) REFERENCES knowledge_books(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_concepts_book
    ON extracted_concepts(book_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS skill_knowledge_links (
        id TEXT PRIMARY KEY,
        skill_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        concept_id TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skill_registry (
        id TEXT PRIMARY KEY,
        slug TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL,
        mode_binding TEXT,
        version INTEGER NOT NULL,
        parent_skill_id TEXT,
        package_json TEXT NOT NULL,
        approved_at TEXT,
        approved_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_skill_registry_slug
    ON skill_registry(slug)
    """,
    """
    CREATE TABLE IF NOT EXISTS skill_versions (
        id TEXT PRIMARY KEY,
        skill_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        status TEXT,
        package_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        note TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skill_evaluations (
        id TEXT PRIMARY KEY,
        skill_id TEXT NOT NULL,
        version INTEGER,
        baseline_skill_id TEXT,
        metrics_json TEXT,
        passed INTEGER,
        notes TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS acquisition_logs (
        id TEXT PRIMARY KEY,
        action TEXT NOT NULL,
        actor TEXT,
        entity_type TEXT,
        entity_id TEXT,
        detail_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
)
