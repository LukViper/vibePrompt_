"""Book metadata helpers."""

from __future__ import annotations

from typing import Any

from app.knowledge.catalog import TARGET_BOOKS, get_catalog_entry


def normalize_title(title: str) -> str:
    return " ".join(title.lower().split())


def find_catalog_match(*, title: str | None = None, slug: str | None = None) -> dict[str, Any] | None:
    if slug:
        return get_catalog_entry(slug)
    if not title:
        return None
    needle = normalize_title(title)
    for book in TARGET_BOOKS:
        if normalize_title(book["title"]) == needle:
            return dict(book)
        if needle in normalize_title(book["title"]):
            return dict(book)
    return None


def acquisition_status_label(entry: dict[str, Any]) -> str:
    if entry.get("full_text_authorized") and entry.get("authorized_download_url"):
        return "authorized_download_available"
    return "manual_or_purchase_required"
