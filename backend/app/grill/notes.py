"""Safe merge helpers for long-form project notes (architecture, data, security, testing)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NoteRevision(BaseModel):
    id: str = Field(default_factory=lambda: f"note_{uuid4().hex[:10]}")
    field: str
    content: str
    status: str = "active"  # active | superseded | proposed
    at: datetime = Field(default_factory=utcnow)
    note: str = ""


@dataclass
class NoteApplyResult:
    value: str
    history_append: list[NoteRevision]
    contradiction: str | None = None
    merged: bool = False


_NORM = re.compile(r"[^a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _NORM.sub(" ", (text or "").lower()).split() if len(t) > 2}


_OPPOSING_PAIRS = (
    ({"monolith", "modular"}, {"microservice", "microservices", "event-sourced", "eventsourced"}),
    ({"sqlite", "synchronous", "sync"}, {"kafka", "streaming", "event-driven"}),
    ({"single", "modular"}, {"polyglot", "federation"}),
    ({"rest", "request"}, {"event-sourced", "cqrs"}),
)


def notes_conflict(existing: str, incoming: str) -> bool:
    """
    Conflict when notes assert opposing architectural directions.
    Complementary additions (low lexical overlap without opposition) are mergeable.
    """
    a, b = (existing or "").strip(), (incoming or "").strip()
    if not a or not b:
        return False
    if a.lower() == b.lower():
        return False
    if a.lower() in b.lower() or b.lower() in a.lower():
        return False
    ta, tb = _tokens(a), _tokens(b)
    for left, right in _OPPOSING_PAIRS:
        if (ta & left and tb & right) or (tb & left and ta & right):
            return True
    return False


def apply_note_update(
    *,
    field: str,
    existing: str,
    incoming: str,
    mode: str | None = None,
) -> NoteApplyResult:
    """
    mode:
      - None / "auto": fill if empty; merge if compatible; conflict → keep existing
      - "append": always append
      - "replace": intentional replacement; previous becomes superseded history
    """
    cleaned = (incoming or "").strip()
    current = (existing or "").strip()
    history: list[NoteRevision] = []
    mode_norm = (mode or "auto").strip().lower()

    if not cleaned:
        return NoteApplyResult(value=current, history_append=[])

    if not current:
        return NoteApplyResult(
            value=cleaned,
            history_append=[
                NoteRevision(field=field, content=cleaned, status="active", note="initial")
            ],
            merged=False,
        )

    if cleaned.lower() == current.lower():
        return NoteApplyResult(value=current, history_append=[])

    if mode_norm == "replace":
        history.append(
            NoteRevision(
                field=field,
                content=current,
                status="superseded",
                note="explicit replacement",
            )
        )
        history.append(
            NoteRevision(
                field=field,
                content=cleaned,
                status="active",
                note="explicit replacement",
            )
        )
        return NoteApplyResult(value=cleaned, history_append=history, merged=False)

    if mode_norm == "append" or (
        mode_norm == "auto" and not notes_conflict(current, cleaned)
    ):
        if cleaned.lower() in current.lower():
            return NoteApplyResult(value=current, history_append=[])
        merged = f"{current.rstrip()}\n\n{cleaned}"
        history.append(
            NoteRevision(
                field=field,
                content=cleaned,
                status="active",
                note="merged append",
            )
        )
        return NoteApplyResult(value=merged, history_append=history, merged=True)

    # Conflict under auto mode — preserve existing; record proposal
    history.append(
        NoteRevision(
            field=field,
            content=cleaned,
            status="proposed",
            note="conflicting update held for confirmation",
        )
    )
    return NoteApplyResult(
        value=current,
        history_append=history,
        contradiction=(
            f"Proposed {field} update conflicts with confirmed notes. "
            "Confirm an explicit replacement or ask to append."
        ),
        merged=False,
    )


def history_to_public(items: list[NoteRevision]) -> list[dict[str, Any]]:
    return [i.model_dump(mode="json") for i in items]
