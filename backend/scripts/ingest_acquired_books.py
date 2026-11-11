#!/usr/bin/env python3
"""Register acquired books/originals into the Knowledge Library and optionally process.

Usage (from backend/):
  .venv-free-tier/bin/python scripts/ingest_acquired_books.py [--process]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge.acquisition.downloader import sha256_file
from app.knowledge.models import BookRecord, BookStatus
from app.knowledge.pipeline.runner import process_book
from app.knowledge.store import KnowledgeStore

MANIFEST = ROOT / "books" / "RESOURCE_MANIFEST.json"
UPLOAD = ROOT / "backend" / "data" / "knowledge" / "uploads"
DB = ROOT / "backend" / "data" / "vibeprompt.db"
SKILLS = ROOT / "backend" / "data" / "skills"

TARGET_SKILL = {
    "adem_yuce_ai_literacy_and_prompt_engineering": "prompt_engineering",
    "adem_yuce_vibe_coding_and_loop_engineering": "agent_engineering",
    "adem_yuce_agent_engineering": "agent_engineering",
    "adem_yuce_ai_native_production": "technical_architecture",
    "prompt_engineering_lee_boonstra": "prompt_engineering",
    "qa_field_manual_suneet_malhotra": "prompt_evaluator",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--process", action="store_true", help="Run extraction pipeline")
    args = parser.parse_args()

    if not MANIFEST.is_file():
        print("Missing", MANIFEST)
        return 1

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    store = KnowledgeStore(str(DB), skills_root=str(SKILLS))
    UPLOAD.mkdir(parents=True, exist_ok=True)

    for resource in manifest.get("resources", []):
        if resource.get("status") != "acquired":
            print("skip", resource.get("id"), resource.get("status"))
            continue
        src = ROOT / resource["local_path"]
        if not src.is_file():
            print("missing file", src)
            continue
        existing = [b for b in store.list_books() if b.catalog_slug == resource["id"]]
        if existing:
            book = existing[0]
            print("exists", book.id, resource["id"])
        else:
            dest_dir = UPLOAD / resource["id"]
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            if not dest.exists():
                dest.write_bytes(src.read_bytes())
            book = BookRecord(
                catalog_slug=resource["id"],
                title=resource.get("title") or resource["id"],
                author=resource.get("author") or "Unknown",
                category="acquired_open",
                description=resource.get("license_note") or "",
                target_skill=TARGET_SKILL.get(resource["id"]),
                source_filename=src.name,
                source_path=str(dest),
                mime_type=(
                    "application/epub+zip"
                    if src.suffix.lower() == ".epub"
                    else "application/pdf"
                ),
                size_bytes=src.stat().st_size,
                sha256=resource.get("sha256") or sha256_file(src),
                source_url=resource.get("source_url") or resource.get("final_url"),
                status=BookStatus.UPLOADED,
                status_detail="Ingested from books/originals",
                usage_permission="owned",
                rights_confirmed=True,
                copyright_note=resource.get("license_note") or "",
            )
            store.create_book(book)
            print("registered", book.id, resource["id"])

        if args.process and book.status != BookStatus.READY:
            job = process_book(store, book.id, actor="ingest_script")
            print("process", book.id, job.status, job.error)

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
