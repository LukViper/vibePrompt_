"""Book-to-Skill knowledge pipeline tests (offline, no pirate downloads)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["FREE_TIER_ENABLED"] = "false"
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("QWEN_API_KEY", None)

from app.api.deps import (
    get_knowledge_store,
    get_settings,
    get_skill_registry,
)
from app.config import Settings, get_settings as _gs
from app.knowledge.acquisition.discovery import build_acquisition_report, discover_all
from app.knowledge.acquisition.downloader import DownloadError, attempt_authorized_download
from app.knowledge.acquisition.licensing import REQUIRED_CONFIRMATION
from app.knowledge.acquisition.source_validator import validate_source_url
from app.knowledge.catalog import TARGET_BOOKS
from app.knowledge.pipeline.runner import process_book
from app.knowledge.store import KnowledgeStore
from app.main import create_app
from app.skills.generator import approve_skill, generate_skill_draft
from app.skills.registry import SkillRegistry
from app.skills.retrieval import retrieve_for_mode


@pytest.fixture()
def tmp_settings(tmp_path: Path) -> Settings:
    get_settings.cache_clear()
    get_knowledge_store.cache_clear()
    get_skill_registry.cache_clear()
    _gs.cache_clear()
    settings = Settings(
        gemini_api_key="",
        openrouter_api_key="",
        groq_api_key="",
        qwen_api_key="",
        free_tier_enabled=False,
        database_path=str(tmp_path / "knowledge.db"),
        knowledge_upload_dir=str(tmp_path / "uploads"),
        skills_dir=str(tmp_path / "skills"),
        api_secret="",
        admin_emails="",
    )
    return settings


@pytest.fixture()
def store(tmp_settings: Settings) -> KnowledgeStore:
    return KnowledgeStore(tmp_settings.database_path, skills_root=tmp_settings.skills_dir)


@pytest.fixture()
def registry(store: KnowledgeStore) -> SkillRegistry:
    return SkillRegistry(store)


@pytest.fixture()
def client(tmp_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    get_settings.cache_clear()
    get_knowledge_store.cache_clear()
    get_skill_registry.cache_clear()
    _gs.cache_clear()

    def _settings() -> Settings:
        return tmp_settings

    monkeypatch.setattr("app.api.deps.get_settings", _settings)
    monkeypatch.setattr("app.config.get_settings", _settings)
    app = create_app()
    app.dependency_overrides[get_settings] = _settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    get_knowledge_store.cache_clear()
    get_skill_registry.cache_clear()


def _register_and_login(client: TestClient) -> str:
    email = "admin@example.com"
    password = "test-password-123"
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    if res.status_code >= 400:
        res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def test_catalog_has_eight_target_books():
    assert len(TARGET_BOOKS) == 8
    slugs = {b["slug"] for b in TARGET_BOOKS}
    assert "the_mom_test" in slugs
    assert "ai_engineering" in slugs


def test_discovery_report_honest_about_no_downloads():
    report = build_acquisition_report()
    assert report["book_count"] == 8
    assert report["authorized_full_text_count"] == 0
    assert report["manual_or_purchase_required_count"] == 8
    for book in report["books"]:
        assert book["downloaded"] is False
        assert book["full_text_authorized"] is False
    assert "manual_or_purchase_required" in report["markdown"]


def test_blocks_pirate_sources():
    bad = validate_source_url("https://libgen.is/book/foo", for_download=True)
    assert bad.ok is False
    good = validate_source_url("https://www.oreilly.com/library/view/x", for_download=False)
    assert good.ok is True


def test_authorized_download_refuses_commercial_titles(tmp_path: Path):
    with pytest.raises(DownloadError) as exc:
        attempt_authorized_download("the_mom_test", tmp_path)
    assert exc.value.code == "not_authorized"


def test_pipeline_extract_generate_approve_retrieve(
    store: KnowledgeStore, registry: SkillRegistry, tmp_path: Path
):
    # Synthetic rights-confirmed "book" — independently authored sample, not a copyrighted work.
    sample = tmp_path / "mom_test_sample.txt"
    sample.write_text(
        """
CHAPTER 1 Asking Better Questions
Always ask about past behaviour rather than hypothetical preferences.
Never use leading questions that embed the answer you want.
The Mom Test principle means talking about their life, not your idea.

CHAPTER 2 Framework for Discovery
Use a simple process: ask, listen, note commitments.
Avoid the pitfall of compliment fishing.
If the user only gives opinions, prefer a decision rule to dig into specifics.
How did you solve this last time? Tell me about the workaround you used.
""",
        encoding="utf-8",
    )

    from app.knowledge.models import BookRecord, BookStatus

    book = BookRecord(
        title="Sample Discovery Notes",
        author="Test",
        catalog_slug="the_mom_test",
        target_skill="customer_discovery",
        source_filename=sample.name,
        source_path=str(sample),
        mime_type="text/plain",
        size_bytes=sample.stat().st_size,
        status=BookStatus.UPLOADED,
        usage_permission="owned",
        rights_confirmed=True,
    )
    store.create_book(book)

    job = process_book(store, book.id, actor="test")
    assert job.status == "succeeded", job.error
    ready = store.get_book(book.id)
    assert ready is not None
    assert ready.status == BookStatus.READY
    assert ready.concept_count > 0
    concepts = store.list_concepts(book.id)
    assert any(c.kind.value == "question_pattern" for c in concepts)

    draft = generate_skill_draft(
        store,
        registry,
        book_ids=[book.id],
        target_slug="customer_discovery",
    )
    assert draft.status.value == "draft"
    assert draft.principles
    pack_dir = Path(store.skills_root) / draft.slug / f"v{draft.version}"
    assert (pack_dir / "skill.md").is_file()
    assert (pack_dir / "principles.md").is_file()
    assert (pack_dir / "sources.json").is_file()

    active = approve_skill(store, registry, draft.id, actor="test")
    assert active.status.value == "active"

    retrieved = retrieve_for_mode(
        registry,
        store,
        mode="conversational",
        user_message="Help me interview customers about invoicing pain",
    )
    assert retrieved["prompt_block"]
    assert "customer_discovery" in retrieved["skills"] or retrieved["principles"]


def test_api_acquisition_and_upload_flow(client: TestClient, tmp_path: Path):
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    report = client.get("/api/knowledge/acquisition-report", headers=headers)
    assert report.status_code == 200
    body = report.json()
    assert body["book_count"] == 8
    assert body["authorized_full_text_count"] == 0

    reg = client.post("/api/knowledge/catalog/the_mom_test/register", headers=headers)
    assert reg.status_code == 200
    book_id = reg.json()["id"]

    sample = tmp_path / "upload.txt"
    sample.write_text(
        "CHAPTER 1 Principles\nAlways ask about past behaviour.\n"
        "Never lead the witness with your idea.\n"
        "How did you handle invoices last month?\n",
        encoding="utf-8",
    )
    with sample.open("rb") as f:
        upload = client.post(
            "/api/knowledge/books/upload",
            headers=headers,
            data={
                "usage_permission": "owned",
                "rights_confirmed": "true",
                "confirmation_text": REQUIRED_CONFIRMATION,
                "catalog_slug": "the_mom_test",
                "book_id": book_id,
            },
            files={"file": ("upload.txt", f, "text/plain")},
        )
    assert upload.status_code == 200, upload.text

    proc = client.post(f"/api/knowledge/books/{book_id}/process", headers=headers)
    assert proc.status_code == 200, proc.text
    assert proc.json()["status"] == "succeeded"

    gen = client.post(
        "/api/knowledge/skills/generate",
        headers=headers,
        json={"book_ids": [book_id], "target_slug": "grill"},
    )
    assert gen.status_code == 200, gen.text
    draft_id = gen.json()["id"]
    assert gen.json()["status"] == "draft"

    ev = client.post(f"/api/knowledge/skills/{draft_id}/evaluate", headers=headers)
    assert ev.status_code == 200
    assert "passed" in ev.json()

    ap = client.post(
        f"/api/knowledge/skills/{draft_id}/approve",
        headers=headers,
        json={"note": "ok"},
    )
    assert ap.status_code == 200
    assert ap.json()["status"] == "active"


def test_upload_without_rights_rejected(client: TestClient, tmp_path: Path):
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    sample = tmp_path / "x.txt"
    sample.write_text("hello principle always ask", encoding="utf-8")
    with sample.open("rb") as f:
        res = client.post(
            "/api/knowledge/books/upload",
            headers=headers,
            data={
                "usage_permission": "owned",
                "rights_confirmed": "false",
                "confirmation_text": "nope",
            },
            files={"file": ("x.txt", f, "text/plain")},
        )
    assert res.status_code == 400


def test_discover_all_shape():
    data = discover_all()
    assert data["policy"]["no_pirate_sources"] is True
    assert len(data["books"]) == 8
