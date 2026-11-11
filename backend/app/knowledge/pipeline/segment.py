"""Chapter / section segmentation with traceability."""

from __future__ import annotations

import re
from typing import Any

CHAPTER_RE = re.compile(
    r"(?im)^(chapter\s+\d+|part\s+\d+|section\s+\d+|[IVXLC]+\.\s+\w+|#\s+.+$|\d+\.\s+[A-Z].{3,80})$"
)


def segment_chapters(text: str, pages: list[str] | None = None) -> list[dict[str, Any]]:
    lines = text.split("\n")
    headings: list[tuple[int, str]] = []
    offset = 0
    line_offsets: list[int] = []
    for line in lines:
        line_offsets.append(offset)
        if CHAPTER_RE.match(line.strip()) or (
            len(line.strip()) < 80
            and line.strip().isupper()
            and len(line.strip()) > 4
            and not line.strip().isdigit()
        ):
            headings.append((offset, line.strip()))
        offset += len(line) + 1

    if not headings:
        # Fallback: split into ~3k char windows
        chunk = 3000
        chapters: list[dict[str, Any]] = []
        for i in range(0, max(len(text), 1), chunk):
            piece = text[i : i + chunk]
            if not piece.strip():
                continue
            chapters.append(
                {
                    "index": len(chapters),
                    "title": f"Section {len(chapters) + 1}",
                    "text": piece.strip(),
                    "char_start": i,
                    "char_end": i + len(piece),
                    "page_start": None,
                    "page_end": None,
                }
            )
        return chapters or [
            {
                "index": 0,
                "title": "Document",
                "text": text,
                "char_start": 0,
                "char_end": len(text),
                "page_start": None,
                "page_end": None,
            }
        ]

    chapters = []
    for i, (start, title) in enumerate(headings):
        end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        # Drop the heading line from body start if duplicated
        body_lines = body.split("\n", 1)
        body_text = body_lines[1].strip() if len(body_lines) > 1 else body
        chapters.append(
            {
                "index": i,
                "title": title[:200],
                "text": body_text,
                "char_start": start,
                "char_end": end,
                "page_start": _page_for_offset(start, pages) if pages else None,
                "page_end": _page_for_offset(end - 1, pages) if pages else None,
            }
        )
    return chapters


def _page_for_offset(offset: int, pages: list[str]) -> int | None:
    cursor = 0
    for i, page in enumerate(pages):
        nxt = cursor + len(page) + 2
        if offset < nxt:
            return i + 1
        cursor = nxt
    return len(pages) if pages else None
