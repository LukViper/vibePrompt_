"""Conservative deterministic extraction for offline / heuristic primary path."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.grill.tech import parse_technology_token
from app.providers.base import StatePatch


@dataclass
class OfflineExtraction:
    patch: StatePatch = field(default_factory=StatePatch)
    notes: list[str] = field(default_factory=list)


_QUESTIONABLE = re.compile(
    r"\b(should we|what about|maybe|perhaps|consider|could we|how about)\b",
    re.I,
)

_SELECT_PATTERNS = [
    re.compile(
        r"\b(?:we(?:'re| are)?\s+using|we(?:'ll| will)\s+use|we have decided to use|"
        r"our (?:database|backend|frontend|stack) will be|database will be|"
        r"using)\s+([A-Za-z0-9.+#\-/]+(?:\s+and\s+[A-Za-z0-9.+#\-/]+)*)",
        re.I,
    ),
    re.compile(
        r"\b(?:tech stack|stack)\s*(?:is|:)\s*([A-Za-z0-9.+#\-/, ]+)",
        re.I,
    ),
]

_REJECT_PATTERNS = [
    re.compile(
        r"\b(?:we\s+)?(?:rejected|reject|won't use|will not use|avoid(?:ing)?)\s+"
        r"([A-Za-z0-9.+#\-/]+)(?:\s+because\s+(.+?))?(?:[.!]|$)",
        re.I,
    ),
]


def _split_tech_list(blob: str) -> list[str]:
    parts = re.split(r"\s+and\s+|,\s*", blob.strip())
    cleaned: list[str] = []
    for p in parts:
        token = p.strip().strip(".,;:!?")
        if token:
            cleaned.append(token)
    return cleaned


def extract_explicit_tech_and_rejections(message: str) -> OfflineExtraction:
    """
    Extract only explicit selections/rejections.
    Questions and brainstorming markers are ignored.
    """
    text = (message or "").strip()
    out = OfflineExtraction()
    if not text or _QUESTIONABLE.search(text):
        # Still allow pure rejection statements that include "because"
        if not re.search(r"\breject(?:ed|ing)?\b", text, re.I):
            return out

    selected: list[str] = []
    for pat in _SELECT_PATTERNS:
        for match in pat.finditer(text):
            for token in _split_tech_list(match.group(1)):
                parsed = parse_technology_token(token)
                if parsed.ambiguous:
                    out.notes.append(f"Skipped ambiguous tech phrase: {token}")
                    continue
                if parsed.canonical and parsed.error != "malformed":
                    selected.append(parsed.canonical)

    # Deduplicate preserving order
    seen: set[str] = set()
    uniq = []
    for s in selected:
        if s.lower() not in seen:
            seen.add(s.lower())
            uniq.append(s)
    if uniq:
        out.patch.tech_stack = uniq

    rejected: list[dict[str, str]] = []
    for pat in _REJECT_PATTERNS:
        for match in pat.finditer(text):
            approach = match.group(1).strip()
            reason = (match.group(2) or "").strip() if match.lastindex and match.lastindex >= 2 else ""
            parsed = parse_technology_token(approach)
            name = parsed.canonical or approach
            if parsed.ambiguous:
                continue
            rejected.append({"approach": name, "reason": reason[:300]})
    if rejected:
        out.patch.add_rejected_approaches = rejected

    return out


def merge_offline_extraction(base: StatePatch, extraction: OfflineExtraction) -> StatePatch:
    """Merge conservative extraction into an existing patch without inventing fields."""
    data = base.model_dump()
    if extraction.patch.tech_stack:
        existing = list(data.get("tech_stack") or [])
        for t in extraction.patch.tech_stack:
            if t not in existing:
                existing.append(t)
        data["tech_stack"] = existing
    if extraction.patch.add_rejected_approaches:
        existing_r = list(data.get("add_rejected_approaches") or [])
        existing_r.extend(extraction.patch.add_rejected_approaches)
        data["add_rejected_approaches"] = existing_r
    return StatePatch.model_validate(data)
