"""Discover legitimate acquisition options for target books."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.knowledge.acquisition.metadata import acquisition_status_label
from app.knowledge.acquisition.source_validator import validate_source_url
from app.knowledge.catalog import TARGET_BOOKS, get_catalog_entry, list_catalog


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def discover_book(slug: str, *, enrich_openlibrary: bool = False) -> dict[str, Any]:
    entry = get_catalog_entry(slug)
    if entry is None:
        return {
            "slug": slug,
            "found": False,
            "error": "Unknown catalog slug",
            "discovered_at": utcnow_iso(),
        }

    sources: list[dict[str, Any]] = []
    for page in entry.get("official_pages") or []:
        v = validate_source_url(page, for_download=False)
        sources.append(
            {
                "kind": "official_page",
                "url": page,
                "valid": v.ok,
                "validation": v.reason,
            }
        )
    for opt in entry.get("legal_options") or []:
        url = opt.get("url")
        v = validate_source_url(url, for_download=False) if url else None
        sources.append(
            {
                "kind": opt.get("kind"),
                "label": opt.get("label"),
                "url": url,
                "valid": True if url is None else (v.ok if v else False),
                "validation": "no URL (manual)" if url is None else (v.reason if v else "n/a"),
            }
        )

    openlibrary: dict[str, Any] | None = None
    if enrich_openlibrary:
        openlibrary = _lookup_openlibrary(entry["title"], entry["author"])

    status = acquisition_status_label(entry)
    return {
        "slug": entry["slug"],
        "found": True,
        "title": entry["title"],
        "author": entry["author"],
        "publisher": entry.get("publisher"),
        "isbn": entry.get("isbn"),
        "year": entry.get("year"),
        "formats": entry.get("formats") or [],
        "target_skill": entry["target_skill"],
        "purpose": entry.get("purpose"),
        "official_pages": entry.get("official_pages") or [],
        "sources": sources,
        "availability_status": status,
        "full_text_authorized": bool(entry.get("full_text_authorized")),
        "authorized_download_url": entry.get("authorized_download_url"),
        "licensing_notes": entry.get("licensing_notes"),
        "legal_acquisition_options": entry.get("legal_options") or [],
        "openlibrary": openlibrary,
        "downloaded": False,  # discovery never claims a download
        "discovered_at": utcnow_iso(),
    }


def discover_all(*, enrich_openlibrary: bool = False) -> dict[str, Any]:
    books = [discover_book(b["slug"], enrich_openlibrary=enrich_openlibrary) for b in TARGET_BOOKS]
    authorized = sum(1 for b in books if b.get("full_text_authorized"))
    return {
        "generated_at": utcnow_iso(),
        "book_count": len(books),
        "authorized_full_text_count": authorized,
        "manual_or_purchase_required_count": len(books) - authorized,
        "policy": {
            "no_pirate_sources": True,
            "no_drm_bypass": True,
            "no_fabricated_downloads": True,
            "preview_is_not_full_text": True,
        },
        "books": books,
        "catalog_slugs": [b["slug"] for b in list_catalog()],
    }


def build_acquisition_report(*, enrich_openlibrary: bool = False) -> dict[str, Any]:
    """Human-oriented acquisition report for all eight target books."""
    raw = discover_all(enrich_openlibrary=enrich_openlibrary)
    lines: list[str] = [
        "# VibePrompt Book Acquisition Report",
        "",
        f"Generated: {raw['generated_at']}",
        "",
        "Policy: only legitimate sources; no torrents, pirate repos, or DRM bypass. "
        "A Google Books preview is not a full-text download right.",
        "",
    ]
    for book in raw["books"]:
        lines.append(f"## {book['title']}")
        lines.append(f"- Author: {book['author']}")
        lines.append(f"- Publisher: {book.get('publisher')}")
        lines.append(f"- ISBN: {book.get('isbn')}")
        lines.append(f"- Year: {book.get('year')}")
        lines.append(f"- Target skill: `{book['target_skill']}`")
        lines.append(f"- Availability: **{book['availability_status']}**")
        lines.append(f"- Full-text authorized download: {book['full_text_authorized']}")
        lines.append(f"- Downloaded: {book['downloaded']} (discovery does not download)")
        lines.append(f"- Licensing: {book.get('licensing_notes')}")
        lines.append("- Legal options:")
        for opt in book.get("legal_acquisition_options") or []:
            url = opt.get("url") or "(seek via local library / retailer)"
            lines.append(f"  - [{opt.get('kind')}] {opt.get('label')}: {url}")
        lines.append("")
    lines.append("## Summary")
    lines.append(
        f"- {raw['book_count']} target books surveyed; "
        f"{raw['authorized_full_text_count']} with authorized free full-text; "
        f"{raw['manual_or_purchase_required_count']} require purchase, "
        "library lending, or rights-confirmed manual upload."
    )
    return {
        **raw,
        "markdown": "\n".join(lines),
    }


def _lookup_openlibrary(title: str, author: str) -> dict[str, Any]:
    """Optional metadata enrichment via Open Library (no full-text fetch)."""
    q = f"title:{title} author:{author}"
    url = "https://openlibrary.org/search.json"
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(url, params={"q": q, "limit": 3})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        return {"ok": False, "error": str(exc)}

    docs = data.get("docs") or []
    results = []
    for doc in docs[:3]:
        results.append(
            {
                "title": doc.get("title"),
                "author_name": doc.get("author_name"),
                "first_publish_year": doc.get("first_publish_year"),
                "isbn": (doc.get("isbn") or [None])[0],
                "key": doc.get("key"),
                "edition_count": doc.get("edition_count"),
            }
        )
    return {"ok": True, "results": results, "note": "Metadata only; not a download authorization."}
