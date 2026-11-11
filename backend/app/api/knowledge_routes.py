"""Knowledge Library + Book-to-Skill admin API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import get_knowledge_store, get_settings, get_skill_registry, require_admin
from app.auth.models import UserRecord
from app.config import Settings
from app.knowledge.acquisition.discovery import build_acquisition_report, discover_all, discover_book
from app.knowledge.acquisition.downloader import DownloadError, attempt_authorized_download
from app.knowledge.acquisition.licensing import REQUIRED_CONFIRMATION, evaluate_rights
from app.knowledge.catalog import get_catalog_entry, list_catalog
from app.knowledge.files import FileValidationError, store_upload
from app.knowledge.models import (
    AssociateSkillsRequest,
    BookCreate,
    BookPreview,
    BookRecord,
    BookStatus,
    BookUpdate,
    KnowledgeConcept,
    KnowledgeKind,
)
from app.knowledge.pipeline.runner import process_book
from app.knowledge.store import KnowledgeStore
from app.skills.evaluate import evaluate_skill
from app.skills.generator import (
    approve_skill,
    generate_skill_draft,
    reject_skill,
    rollback_skill,
)
from app.skills.models import (
    SkillApproveRequest,
    SkillDraftRequest,
    SkillPackage,
    SkillRollbackRequest,
    SkillSummary,
)
from app.skills.registry import SkillRegistry

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _actor(user: UserRecord) -> str:
    return user.email


# ---------------------------------------------------------------------------
# Discovery / acquisition
# ---------------------------------------------------------------------------


@router.get("/catalog")
def catalog(_: UserRecord = Depends(require_admin)) -> list[dict[str, Any]]:
    return list_catalog()


@router.get("/discovery")
def discovery_all(
    enrich: bool = False,
    _: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    return discover_all(enrich_openlibrary=enrich)


@router.get("/discovery/{slug}")
def discovery_one(
    slug: str,
    enrich: bool = False,
    _: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    result = discover_book(slug, enrich_openlibrary=enrich)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail="Unknown catalog slug")
    return result


@router.get("/acquisition-report")
def acquisition_report(
    enrich: bool = False,
    _: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    return build_acquisition_report(enrich_openlibrary=enrich)


@router.post("/catalog/{slug}/register")
def register_from_catalog(
    slug: str,
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> BookRecord:
    entry = get_catalog_entry(slug)
    if not entry:
        raise HTTPException(status_code=404, detail="Unknown catalog slug")
    existing = [b for b in store.list_books() if b.catalog_slug == slug]
    if existing:
        return existing[0]
    book = BookRecord(
        catalog_slug=slug,
        title=entry["title"],
        author=entry["author"],
        category=entry.get("category") or "general",
        description=entry.get("purpose") or "",
        isbn=entry.get("isbn"),
        publisher=entry.get("publisher"),
        year=entry.get("year"),
        target_skill=entry.get("target_skill"),
        status=BookStatus.AWAITING_FILE,
        status_detail="Registered from catalog — awaiting authorized file",
        copyright_note=entry.get("licensing_notes") or "",
        usage_permission="unknown",
        created_by=user.id,
    )
    store.create_book(book)
    store.audit(
        "register_catalog_book",
        actor=_actor(user),
        entity_type="book",
        entity_id=book.id,
        detail={"slug": slug},
    )
    return book


@router.post("/catalog/{slug}/download")
def download_authorized(
    slug: str,
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
    settings: Settings = Depends(get_settings),
) -> BookRecord:
    dest = Path(settings.knowledge_upload_dir) / "authorized"
    try:
        result = attempt_authorized_download(slug, dest)
    except DownloadError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc

    entry = get_catalog_entry(slug) or {}
    book = BookRecord(
        catalog_slug=slug,
        title=entry.get("title") or slug,
        author=entry.get("author") or "Unknown",
        category=entry.get("category") or "general",
        description=entry.get("purpose") or "",
        isbn=entry.get("isbn"),
        publisher=entry.get("publisher"),
        year=entry.get("year"),
        target_skill=entry.get("target_skill"),
        source_filename=result["filename"],
        source_path=result["path"],
        mime_type=result.get("content_type"),
        size_bytes=int(result["size_bytes"]),
        sha256=result["sha256"],
        source_url=result["source_url"],
        status=BookStatus.UPLOADED,
        status_detail="Authorized download stored",
        usage_permission="open_access",
        rights_confirmed=True,
        copyright_note=entry.get("licensing_notes") or "",
        created_by=user.id,
    )
    dup = store.find_by_sha256(book.sha256 or "")
    if dup:
        raise HTTPException(status_code=409, detail=f"Duplicate of book {dup.id}")
    store.create_book(book)
    store.audit(
        "authorized_download",
        actor=_actor(user),
        entity_type="book",
        entity_id=book.id,
        detail={"slug": slug, "sha256": book.sha256},
    )
    return book


# ---------------------------------------------------------------------------
# Books CRUD + upload + process
# ---------------------------------------------------------------------------


@router.get("/books", response_model=list[BookRecord])
def list_books(
    skill: str | None = None,
    status: str | None = None,
    q: str | None = None,
    _: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> list[BookRecord]:
    return store.list_books(skill=skill, status=status, q=q)


@router.post("/books", response_model=BookRecord)
def create_book(
    body: BookCreate,
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> BookRecord:
    book = BookRecord(
        **body.model_dump(),
        status=BookStatus.AWAITING_FILE,
        status_detail="Metadata created — awaiting file",
        created_by=user.id,
    )
    if body.catalog_slug:
        entry = get_catalog_entry(body.catalog_slug)
        if entry:
            book.isbn = book.isbn or entry.get("isbn")
            book.publisher = book.publisher or entry.get("publisher")
            book.year = book.year or entry.get("year")
            book.target_skill = book.target_skill or entry.get("target_skill")
    store.create_book(book)
    store.audit("create_book", actor=_actor(user), entity_type="book", entity_id=book.id)
    return book


@router.get("/books/{book_id}", response_model=BookPreview)
def get_book(
    book_id: str,
    _: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> BookPreview:
    book = store.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    chapters = store.list_chapters(book_id)
    # Truncate chapter text in preview
    slim = [{**c, "text": (c.get("preview") or c.get("text", "")[:400])} for c in chapters]
    return BookPreview(
        book=book,
        text_preview=store.get_text_preview(book_id),
        chapters=slim,
        concepts=store.list_concepts(book_id),
        latest_job=store.latest_job(book_id),
    )


@router.patch("/books/{book_id}", response_model=BookRecord)
def update_book(
    book_id: str,
    body: BookUpdate,
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> BookRecord:
    book = store.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(book, k, v)
    store.update_book(book)
    store.audit("update_book", actor=_actor(user), entity_type="book", entity_id=book_id, detail=data)
    return book


@router.post("/books/{book_id}/archive", response_model=BookRecord)
def archive_book(
    book_id: str,
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> BookRecord:
    book = store.archive_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    store.audit("archive_book", actor=_actor(user), entity_type="book", entity_id=book_id)
    return book


@router.post("/books/upload", response_model=BookRecord)
async def upload_book(
    file: UploadFile = File(...),
    usage_permission: str = Form("owned"),
    rights_confirmed: bool = Form(False),
    confirmation_text: str = Form(""),
    catalog_slug: str | None = Form(None),
    title: str | None = Form(None),
    author: str | None = Form(None),
    target_skill: str | None = Form(None),
    category: str | None = Form(None),
    description: str = Form(""),
    copyright_note: str = Form(""),
    book_id: str | None = Form(None),
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
    settings: Settings = Depends(get_settings),
) -> BookRecord:
    if not rights_confirmed or confirmation_text.strip() != REQUIRED_CONFIRMATION:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "rights_confirmation_required",
                "message": "Confirm rights using the exact confirmation text.",
                "required_confirmation": REQUIRED_CONFIRMATION,
            },
        )
    decision = evaluate_rights(
        usage_permission=usage_permission,
        rights_confirmed=True,
    )
    if not decision.allowed:
        raise HTTPException(status_code=400, detail=decision.reason)

    data = await file.read()
    entry = get_catalog_entry(catalog_slug) if catalog_slug else None

    book: BookRecord | None = store.get_book(book_id) if book_id else None
    if book is None:
        book = BookRecord(
            catalog_slug=catalog_slug,
            title=title or (entry["title"] if entry else (file.filename or "Untitled")),
            author=author or (entry["author"] if entry else "Unknown"),
            category=category or (entry.get("category") if entry else "general") or "general",
            description=description or (entry.get("purpose") if entry else "") or "",
            target_skill=target_skill or (entry.get("target_skill") if entry else None),
            isbn=entry.get("isbn") if entry else None,
            publisher=entry.get("publisher") if entry else None,
            year=entry.get("year") if entry else None,
            copyright_note=copyright_note or (entry.get("licensing_notes") if entry else "") or "",
            usage_permission=usage_permission,
            rights_confirmed=True,
            status=BookStatus.UPLOADED,
            created_by=user.id,
        )
        store.create_book(book)

    try:
        stored = store_upload(
            upload_root=Path(settings.knowledge_upload_dir),
            book_id=book.id,
            filename=file.filename or "upload.bin",
            data=data,
            max_bytes=settings.knowledge_max_upload_bytes,
        )
    except FileValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    dup = store.find_by_sha256(str(stored["sha256"]))
    if dup and dup.id != book.id:
        raise HTTPException(status_code=409, detail=f"Duplicate of book {dup.id}")

    book.source_filename = str(stored["filename"])
    book.source_path = str(stored["path"])
    book.mime_type = str(stored["mime_type"])
    book.size_bytes = int(stored["size_bytes"])
    book.sha256 = str(stored["sha256"])
    book.usage_permission = usage_permission
    book.rights_confirmed = True
    book.status = BookStatus.UPLOADED
    book.status_detail = "Uploaded — ready to process"
    store.update_book(book)
    store.audit(
        "upload_book",
        actor=_actor(user),
        entity_type="book",
        entity_id=book.id,
        detail={"filename": book.source_filename, "sha256": book.sha256},
    )
    return book


@router.post("/books/{book_id}/process")
def process(
    book_id: str,
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> dict[str, Any]:
    if not store.get_book(book_id):
        raise HTTPException(status_code=404, detail="Book not found")
    job = process_book(store, book_id, actor=_actor(user))
    return job.model_dump(mode="json")


@router.post("/books/{book_id}/associate-skills", response_model=BookRecord)
def associate_skills(
    book_id: str,
    body: AssociateSkillsRequest,
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> BookRecord:
    book = store.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    book.associated_skill_ids = list(dict.fromkeys(body.skill_ids))
    store.update_book(book)
    store.audit(
        "associate_skills",
        actor=_actor(user),
        entity_type="book",
        entity_id=book_id,
        detail={"skill_ids": body.skill_ids},
    )
    return book


@router.patch("/concepts/{concept_id}", response_model=KnowledgeConcept)
def edit_concept(
    concept_id: str,
    body: dict[str, Any],
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> KnowledgeConcept:
    # Find concept across books
    for book in store.list_books(include_archived=True):
        for c in store.list_concepts(book.id):
            if c.id == concept_id:
                if "title" in body:
                    c.title = str(body["title"])
                if "summary" in body:
                    c.summary = str(body["summary"])
                if "application" in body:
                    c.application = str(body["application"])
                if "kind" in body:
                    c.kind = KnowledgeKind(body["kind"])
                if "confidence" in body:
                    c.confidence = float(body["confidence"])
                if "chapter_ref" in body:
                    c.chapter_ref = body["chapter_ref"]
                store.update_concept(c)
                store.audit(
                    "edit_concept",
                    actor=_actor(user),
                    entity_type="concept",
                    entity_id=concept_id,
                )
                return c
    raise HTTPException(status_code=404, detail="Concept not found")


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


@router.get("/skills", response_model=list[SkillSummary])
def list_skills(
    _: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> list[SkillSummary]:
    registry.ensure_builtins()
    return store.list_skills()


@router.get("/skills/{skill_id}", response_model=SkillPackage)
def get_skill(
    skill_id: str,
    _: UserRecord = Depends(require_admin),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> SkillPackage:
    skill = registry.get(skill_id) or registry.get_by_slug(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.post("/skills/generate", response_model=SkillPackage)
def generate_skill(
    body: SkillDraftRequest,
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> SkillPackage:
    book_ids = list(body.book_ids)
    if body.book_id:
        book_ids.append(body.book_id)
    book_ids = list(dict.fromkeys(book_ids))
    try:
        return generate_skill_draft(
            store,
            registry,
            book_ids=book_ids,
            target_skill_id=body.target_skill_id,
            target_slug=body.target_slug,
            name=body.name,
            mode_binding=body.mode_binding,
            actor=_actor(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skills/{skill_id}/approve", response_model=SkillPackage)
def approve(
    skill_id: str,
    body: SkillApproveRequest,
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> SkillPackage:
    try:
        return approve_skill(
            store, registry, skill_id, actor=_actor(user), note=body.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skills/{skill_id}/reject", response_model=SkillPackage)
def reject(
    skill_id: str,
    body: SkillApproveRequest,
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> SkillPackage:
    try:
        return reject_skill(
            store, registry, skill_id, actor=_actor(user), note=body.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/skills/{skill_id}/versions")
def skill_versions(
    skill_id: str,
    _: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> list[dict[str, Any]]:
    return store.list_skill_versions(skill_id)


@router.post("/skills/{skill_id}/rollback", response_model=SkillPackage)
def rollback(
    skill_id: str,
    body: SkillRollbackRequest,
    user: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> SkillPackage:
    try:
        return rollback_skill(
            store,
            registry,
            skill_id,
            body.version,
            actor=_actor(user),
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skills/{skill_id}/evaluate")
def evaluate(
    skill_id: str,
    _: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> dict[str, Any]:
    skill = registry.get(skill_id) or registry.get_by_slug(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    baseline = None
    if skill.parent_skill_id:
        baseline = registry.get(skill.parent_skill_id)
    return evaluate_skill(registry, store, skill, baseline=baseline)


@router.get("/audit")
def audit_log(
    limit: int = 100,
    _: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
) -> list[dict[str, Any]]:
    rows = store.list_audit(limit=limit)
    # Parse detail_json for clients
    out = []
    for r in rows:
        item = dict(r)
        try:
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
        except json.JSONDecodeError:
            item["detail"] = {}
        out.append(item)
    return out


@router.get("/rights-confirmation")
def rights_confirmation_text(_: UserRecord = Depends(require_admin)) -> dict[str, str]:
    return {"required_confirmation": REQUIRED_CONFIRMATION}


@router.post("/orchestrate/preview")
def orchestrate_preview(
    body: dict[str, Any],
    _: UserRecord = Depends(require_admin),
    store: KnowledgeStore = Depends(get_knowledge_store),
    registry: SkillRegistry = Depends(get_skill_registry),
) -> dict[str, Any]:
    """Preview which skills would activate for a message (admin debugging)."""
    from app.skills.orchestrator import build_orchestration_context

    message = str(body.get("message") or "")
    mode = str(body.get("mode") or "conversational")
    selected = body.get("user_selected")
    if selected is not None and not isinstance(selected, list):
        raise HTTPException(status_code=400, detail="user_selected must be a list")
    plan = build_orchestration_context(
        registry,
        store,
        mode=mode,
        user_message=message,
        user_selected=selected,
    )
    return {
        "mode": plan.mode,
        "selected_slugs": plan.selected_slugs,
        "reasons": plan.reasons,
        "skills": plan.skills,
        "principles": plan.principles,
        "prompt_block": plan.prompt_block,
    }
