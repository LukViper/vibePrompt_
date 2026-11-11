"""Conversation summarization, working memory, and token-aware context assembly.

Structured ProjectState remains authoritative. Summaries never write back into
decisions, tech selections, or other confirmed fields.

Re-exports ConversationSummary / WorkingMemory from projects.models for callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.grill.modes import BehaviouralMode, canonical_mode
from app.projects.models import (
    ConversationSummary,
    FindingStatus,
    Message,
    ProjectState,
    WorkingMemory,
    utcnow,
)


@dataclass
class AssembledContext:
    """Prompt-ready assembly with budget accounting."""

    snapshot: dict[str, Any]
    conversation_tail: list[dict[str, str]]
    estimated_chars: int = 0
    truncated_messages: int = 0
    notes: list[str] = field(default_factory=list)
    excluded_message_ids: list[str] = field(default_factory=list)
    active_message_ids: list[str] = field(default_factory=list)
    summary_before_truncation: str = ""
    summary_after_truncation: str = ""
    summary_truncated: bool = False
    diagnostics: Any | None = None


_NORM = re.compile(r"[^a-z0-9]+")
_CORRECTION_RE = re.compile(
    r"\b(actually|correction|instead|change that|we decided|explicitly|"
    r"replace|not that|ignore (the )?previous)\b",
    re.I,
)
_EXCLUSION_RE = re.compile(
    r"\b(?:exclud(?:e|ing)|without|ignore|do not (?:discuss|mention|bring up)|"
    r"don'?t (?:discuss|mention|bring up)|leave out|aside from)\s+"
    r"([A-Za-z][\w\-]*(?:\s+[A-Za-z][\w\-]*){0,3})",
    re.I,
)


def _tokens(text: str) -> set[str]:
    return {t for t in _NORM.sub(" ", (text or "").lower()).split() if len(t) > 2}


def estimate_chars(*parts: str) -> int:
    return sum(len(p or "") for p in parts)


def extract_turn_exclusions(user_message: str) -> list[str]:
    """Parse explicit exclusions from the latest user message."""
    stop_tail = {
        "from",
        "for",
        "in",
        "on",
        "at",
        "to",
        "this",
        "that",
        "the",
        "a",
        "an",
        "my",
        "our",
        "question",
        "discussion",
        "topic",
        "please",
    }
    found: list[str] = []
    for match in _EXCLUSION_RE.finditer(user_message or ""):
        phrase = (match.group(1) or "").strip().strip(".,;:!?")
        parts = phrase.split()
        trimmed: list[str] = []
        for part in parts:
            if part.lower() in stop_tail and trimmed:
                break
            if part.lower() in stop_tail and not trimmed:
                continue
            trimmed.append(part)
        phrase = " ".join(trimmed).strip()
        low = phrase.lower()
        if not phrase or low in stop_tail:
            continue
        if phrase.lower() not in {f.lower() for f in found}:
            found.append(phrase[:80])
    return found[:8]


def update_working_memory(
    project: ProjectState,
    *,
    user_message: str,
    intent: str | None,
    mode: BehaviouralMode | str,
) -> WorkingMemory:
    """Refresh ephemeral working memory from the latest turn + structured state."""
    mode_val = mode.value if isinstance(mode, BehaviouralMode) else str(mode)
    wm = getattr(project, "working_memory", None) or WorkingMemory()
    wm.current_intent = intent
    wm.active_mode = canonical_mode(mode_val).value
    wm.unresolved_questions = [
        q.text for q in project.open_questions if not q.answered
    ][:12]
    if project.outstanding_tasks:
        wm.current_task = project.outstanding_tasks[0]
    elif project.milestones and not project.completed_milestones:
        wm.current_task = project.milestones[0]
    if _CORRECTION_RE.search(user_message or ""):
        wm.last_user_correction = (user_message or "").strip()[:500]
    # Exclusions are turn-scoped — replace each turn so stale exclusions do not linger forever
    wm.turn_exclusions = extract_turn_exclusions(user_message)
    wm.updated_at = utcnow()
    project.working_memory = wm
    return wm


def should_summarize(
    project: ProjectState,
    *,
    min_messages: int = 16,
    min_new_since_summary: int = 8,
    max_unsummarized_chars: int = 24_000,
) -> bool:
    """Trigger summarization only when conversation growth warrants it."""
    msgs = project.messages or []
    n = len(msgs)
    if n < min_messages:
        return False
    summary = getattr(project, "conversation_summary", None)
    covered = int(getattr(summary, "covered_message_count", 0) or 0) if summary else 0
    new_count = n - covered
    if new_count < min_new_since_summary:
        return False
    # Char budget on messages older than a small recent window
    older = msgs[:-6] if n > 6 else []
    older_chars = sum(len(m.content or "") for m in older)
    return older_chars >= max_unsummarized_chars // 3 or new_count >= min_new_since_summary


def _decision_status_label(status: str | None) -> str:
    from app.projects.models import normalize_decision_status, DecisionStatus

    s = normalize_decision_status(status)
    if s == DecisionStatus.CONFIRMED.value:
        return "confirmed"
    if s == DecisionStatus.PROVISIONALLY_ACCEPTED.value:
        return "provisionally_accepted"
    if s == DecisionStatus.PROPOSED.value:
        return "proposed"
    if s == DecisionStatus.UNVERIFIED.value:
        return "unverified"
    if s == DecisionStatus.REJECTED.value:
        return "rejected"
    if s == DecisionStatus.RESOLVED.value:
        return "resolved"
    if s == DecisionStatus.SUPERSEDED.value:
        return "superseded"
    return s


def _structured_memory_digest(project: ProjectState) -> str:
    """Authoritative facts — preferred over free-form message paraphrase.

    Confirmed / proposed / rejected / unresolved stay distinctly labeled so
    compression cannot promote mentor proposals into confirmed decisions.
    """
    lines: list[str] = []
    if project.objective:
        lines.append(f"Objective: {project.objective}")
    if getattr(project, "problem_statement", ""):
        lines.append(f"Problem: {project.problem_statement}")
    if project.intended_users:
        lines.append("Users: " + ", ".join(project.intended_users))
    if project.tech_stack:
        lines.append("Tech stack: " + ", ".join(project.tech_stack))

    by_status: dict[str, list[str]] = {}
    for d in project.decisions or []:
        label = _decision_status_label(getattr(d, "status", None))
        by_status.setdefault(label, []).append(f"{d.title}={d.choice}")
    # Emit in stable priority order — never fold proposed into confirmed
    for key, heading in (
        ("confirmed", "Confirmed decisions"),
        ("provisionally_accepted", "Provisionally accepted decisions"),
        ("proposed", "Proposed decisions (not user-approved)"),
        ("unverified", "Unverified decisions"),
        ("resolved", "Resolved decisions"),
        ("rejected", "Rejected decisions"),
        ("superseded", "Superseded decisions (history)"),
    ):
        items = by_status.get(key) or []
        if items:
            lines.append(f"{heading}: " + "; ".join(items[:12]))

    rejected = getattr(project, "rejected_approaches", []) or []
    if rejected:
        lines.append(
            "Rejected approaches: "
            + "; ".join(
                f"{r.approach}" + (f" ({r.reason})" if r.reason else "")
                for r in rejected[:10]
            )
        )
    if project.constraints:
        lines.append(
            "Constraints: " + "; ".join(c.text for c in project.constraints[:8])
        )
    open_q = [q.text for q in project.open_questions if not q.answered][:8]
    if open_q:
        lines.append("Unresolved questions: " + "; ".join(open_q))
    if project.outstanding_tasks:
        lines.append("Outstanding: " + "; ".join(project.outstanding_tasks[:8]))
    if project.completed_milestones:
        lines.append("Completed: " + "; ".join(project.completed_milestones[:8]))
    if project.architecture_notes:
        lines.append("Architecture: " + project.architecture_notes[:600])
    prefs = list(getattr(project, "preferences", []) or [])
    if prefs:
        lines.append("Preferences: " + "; ".join(prefs[:8]))
    return "\n".join(lines)


def _message_digest(messages: list[Message], *, max_items: int = 20) -> str:
    """Compact older turns — facts/cues only, not treated as decisions."""
    lines: list[str] = []
    for m in messages[-max_items:]:
        role = m.role
        content = (m.content or "").strip().replace("\n", " ")
        if len(content) > 220:
            content = content[:217] + "..."
        if not content:
            continue
        tag = ""
        low = content.lower()
        if any(w in low for w in ("maybe", "brainstorm", "what if", "could we")):
            tag = " [brainstorm-cue]"
        if role == "assistant" and any(
            w in low
            for w in (
                "recommend",
                "i'd lean",
                "suggested approach",
                "better alternative",
                "practical path",
            )
        ):
            tag = (tag + " [recommendation-not-decision]").strip()
        mid = getattr(m, "id", "") or ""
        prefix = f"- {role}{tag}"
        if mid:
            prefix += f" {{{mid}}}"
        lines.append(f"{prefix}: {content}")
    return "\n".join(lines)


def scrub_summary_for_exclusions(summary_text: str, exclusions: list[str]) -> str:
    """Remove digest lines that mention turn exclusions; keep structured headings."""
    if not summary_text or not exclusions:
        return summary_text
    needles = [e.lower() for e in exclusions if e]
    out_lines: list[str] = []
    in_digest = False
    for line in summary_text.splitlines():
        if line.startswith("## Earlier conversation digest"):
            in_digest = True
            out_lines.append(line)
            continue
        if line.startswith("## ") and in_digest:
            in_digest = False
        if in_digest and line.startswith("- "):
            low = line.lower()
            if any(n in low for n in needles):
                continue
        out_lines.append(line)
    if exclusions:
        out_lines.append(
            "Turn exclusions (do not recommend unless user reopens): "
            + ", ".join(exclusions)
        )
    return "\n".join(out_lines)


def build_deterministic_summary(
    project: ProjectState,
    *,
    keep_recent: int = 8,
) -> ConversationSummary:
    """
    Build a rolling summary from structured memory + older messages.

    Structured memory is listed first and is authoritative.
    """
    msgs = list(project.messages or [])
    older = msgs[:-keep_recent] if len(msgs) > keep_recent else []
    prev = getattr(project, "conversation_summary", None)
    version = int(getattr(prev, "version", 0) or 0) + 1 if prev and prev.text else 1

    parts = [
        "## Authoritative project memory",
        _structured_memory_digest(project) or "(no structured facts yet)",
    ]
    if older:
        parts.extend(
            [
                "",
                "## Earlier conversation digest (not confirmed decisions)",
                _message_digest(older),
            ]
        )
    text = "\n".join(parts).strip()
    last_id = older[-1].id if older else (msgs[-1].id if msgs else None)
    return ConversationSummary(
        id=getattr(prev, "id", None) or ConversationSummary().id,
        version=version,
        text=text[:12_000],
        covered_through_message_id=last_id,
        covered_message_count=len(msgs),
        source="deterministic",
        created_at=getattr(prev, "created_at", None) or utcnow(),
        updated_at=utcnow(),
    )


def apply_summary_update(
    project: ProjectState,
    new_summary: ConversationSummary | None,
    *,
    failed: bool = False,
) -> ProjectState:
    """
    Safe summary update semantics.
    On failure, keep previous summary and mark source.
    Never mutates decisions/tech/requirements from the summary text.
    """
    if failed:
        prev = getattr(project, "conversation_summary", None)
        if prev is None:
            project.conversation_summary = ConversationSummary(
                text="",
                source="failed_keep_previous",
                covered_message_count=len(project.messages or []),
            )
        else:
            prev.source = "failed_keep_previous"
            prev.updated_at = utcnow()
            project.conversation_summary = prev
        return project

    if new_summary is None:
        return project

    # Integrity: refuse to treat summary as a vehicle to clear structured fields
    # (summary is additive metadata only)
    history = list(getattr(project, "conversation_summary_history", []) or [])
    prev = getattr(project, "conversation_summary", None)
    if prev and prev.text and prev.version != new_summary.version:
        # Keep last few versions for audit
        history.append(prev)
        project.conversation_summary_history = history[-5:]

    project.conversation_summary = new_summary
    return project


def maybe_refresh_summary(
    project: ProjectState,
    *,
    min_messages: int = 16,
    min_new_since_summary: int = 8,
    keep_recent: int = 8,
) -> bool:
    """
    Synchronously refresh summary when triggers fire.
    Returns True if summary was updated.
    """
    if not should_summarize(
        project,
        min_messages=min_messages,
        min_new_since_summary=min_new_since_summary,
    ):
        return False
    try:
        summary = build_deterministic_summary(project, keep_recent=keep_recent)
        apply_summary_update(project, summary, failed=False)
        return True
    except Exception:
        apply_summary_update(project, None, failed=True)
        return False


def select_recent_messages(
    project: ProjectState,
    *,
    user_message: str,
    max_messages: int = 10,
    max_chars_each: int = 1500,
    exclusions: list[str] | None = None,
) -> tuple[list[dict[str, str]], list[str], list[str]]:
    """
    Working-memory message window with light relevance boost.

    Returns (tail_dicts, active_ids, candidate_ids_before_cap).
    Always keeps the most recent turns; may pull 1–2 older relevant turns.
    Exclusion terms block relevance-boost of older turns that match them.
    """
    msgs = list(project.messages or [])
    if not msgs:
        return [], [], []

    excl = [e.lower() for e in (exclusions or []) if e]
    recent = msgs[-(max_messages):]
    query_toks = _tokens(user_message)
    extras: list[Message] = []
    if query_toks and len(msgs) > max_messages:
        scored: list[tuple[int, Message]] = []
        for m in msgs[:-max_messages]:
            content_low = (m.content or "").lower()
            if excl and any(e in content_low for e in excl):
                continue  # do not revive excluded topics via relevance boost
            overlap = len(_tokens(m.content) & query_toks)
            if overlap >= 2:
                scored.append((overlap, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        extras = [m for _, m in scored[:2]]

    seen: set[str] = set()
    ordered: list[Message] = []
    for m in extras + recent:
        if m.id in seen:
            continue
        seen.add(m.id)
        ordered.append(m)
    candidate_ids = [m.id for m in ordered]
    ordered = ordered[-max_messages:]
    out: list[dict[str, str]] = []
    active_ids: list[str] = []
    for m in ordered:
        role = (m.role or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = (m.content or "").strip()[:max_chars_each]
        if content:
            out.append({"role": role, "content": content, "id": m.id})
            active_ids.append(m.id)
    return out, active_ids, candidate_ids


def assemble_prompt_context(
    project: ProjectState,
    *,
    mode: BehaviouralMode | str,
    user_message: str,
    structured_snapshot: dict[str, Any],
    max_recent_messages: int = 10,
    max_chars_each: int = 1500,
    max_summary_chars: int = 4000,
    max_total_chars: int = 28_000,
    enable_diagnostics: bool = True,
) -> AssembledContext:
    """
    Assemble snapshot + conversation tail under a soft char budget.

    Priority when trimming (never drop critical structured constraints first):
    1. Keep structured_snapshot critical keys (with distinct decision statuses)
    2. Trim conversation summary / scrub turn exclusions
    3. Drop oldest messages in the active window (keep ≥2)
    """
    import json
    import uuid

    from app.grill.context import retrieve_relevant_context
    from app.grill.context_diagnostics import (
        ContextDiagnostics,
        record_diagnostics,
        snapshot_excerpt,
    )
    from app.projects.models import DecisionStatus, normalize_decision_status

    notes: list[str] = []
    snapshot = dict(structured_snapshot)

    wm = getattr(project, "working_memory", None)
    exclusions = list(getattr(wm, "turn_exclusions", None) or []) if wm else []
    if wm:
        snapshot["working_memory"] = {
            "current_intent": wm.current_intent,
            "active_mode": wm.active_mode,
            "unresolved_questions": list(wm.unresolved_questions)[:8],
            "current_task": wm.current_task,
            "last_user_correction": wm.last_user_correction or None,
            "turn_exclusions": exclusions,
        }

    summary = getattr(project, "conversation_summary", None)
    summary_before = ""
    summary_text = ""
    summary_truncated = False
    summary_reused = bool(summary and summary.text)
    if summary and summary.text:
        summary_before = summary.text
        summary_text = scrub_summary_for_exclusions(
            summary.text[:max_summary_chars], exclusions
        )
        snapshot["conversation_summary"] = {
            "version": summary.version,
            "source": summary.source,
            "text": summary_text,
            "note": (
                "Summary is continuity aid only. "
                "Confirmed decisions/tech/rejections in structured fields are authoritative. "
                "Lines tagged [recommendation-not-decision] are not project decisions."
            ),
        }
        notes.append("Structured project memory overrides summary if they disagree.")
        if exclusions:
            notes.append(
                "Turn exclusions applied to conversation digest: " + ", ".join(exclusions)
            )

    # Critical keys with distinct statuses — never collapse proposed → confirmed
    critical_decisions = []
    for d in project.decisions or []:
        status = normalize_decision_status(getattr(d, "status", None))
        if status == DecisionStatus.SUPERSEDED.value:
            continue
        critical_decisions.append(
            {
                "title": d.title,
                "choice": d.choice,
                "status": status,
                "source": getattr(d, "source", "") or "",
            }
        )
    critical = {
        "tech_stack": list(project.tech_stack),
        "rejected_approaches": [
            {"approach": r.approach, "reason": r.reason}
            for r in getattr(project, "rejected_approaches", []) or []
        ],
        "decisions": critical_decisions[:20],
    }
    for k, v in critical.items():
        snapshot[k] = v

    tail, active_ids, candidate_ids = select_recent_messages(
        project,
        user_message=user_message,
        max_messages=max_recent_messages,
        max_chars_each=max_chars_each,
        exclusions=exclusions,
    )

    snap_json = json.dumps(snapshot, default=str)
    est = len(snap_json) + sum(len(t["content"]) for t in tail) + len(user_message)
    truncated = 0
    excluded_ids: list[str] = []

    while est > max_total_chars and summary_text and len(summary_text) > 400:
        summary_text = summary_text[: max(400, len(summary_text) // 2)]
        summary_truncated = True
        if "conversation_summary" in snapshot:
            snapshot["conversation_summary"]["text"] = summary_text
        snap_json = json.dumps(snapshot, default=str)
        est = len(snap_json) + sum(len(t["content"]) for t in tail) + len(user_message)
        notes.append("Conversation summary truncated to fit context budget.")

    while est > max_total_chars and len(tail) > 2:
        dropped = tail.pop(0)
        truncated += 1
        dropped_id = dropped.get("id") or ""
        if dropped_id:
            excluded_ids.append(dropped_id)
            if dropped_id in active_ids:
                active_ids.remove(dropped_id)
        est = len(snap_json) + sum(len(t["content"]) for t in tail) + len(user_message)

    if truncated:
        notes.append(f"Excluded {truncated} older message(s) from active window.")

    try:
        bundle = retrieve_relevant_context(project, mode=mode, user_message=user_message)
        notes.extend(bundle.notes)
    except Exception:
        pass

    # Strip id from tail before model (providers expect role/content only)
    model_tail = [{"role": t["role"], "content": t["content"]} for t in tail]

    project_facts = [
        {
            "kind": "decision",
            "title": d["title"],
            "choice": d["choice"],
            "status": d["status"],
            "provenance": d.get("source") or "project_state",
        }
        for d in critical_decisions[:20]
    ]
    for r in getattr(project, "rejected_approaches", []) or []:
        project_facts.append(
            {
                "kind": "rejected_approach",
                "approach": r.approach,
                "reason": r.reason,
                "provenance": "project_state",
            }
        )

    diag = None
    if enable_diagnostics:
        keys, _ = snapshot_excerpt(snapshot)
        diag = ContextDiagnostics(
            request_id=uuid.uuid4().hex[:12],
            user_message=user_message,
            active_message_ids=list(active_ids),
            active_messages=[
                {"id": t.get("id", ""), "role": t["role"], "content": t["content"]}
                for t in tail
            ],
            summary_before_truncation=summary_before[:4000],
            summary_after_truncation=summary_text[:4000],
            summary_truncated=summary_truncated,
            summary_version=getattr(summary, "version", None) if summary else None,
            summary_reused=summary_reused and not summary_truncated,
            excluded_message_ids=excluded_ids,
            truncated_message_count=truncated,
            project_facts=project_facts,
            turn_exclusions=exclusions,
            primary_snapshot_keys=keys,
            primary_summary_excerpt=summary_text[:800],
            assembly_notes=list(notes),
            estimated_chars=est,
        )
        record_diagnostics(diag, emit=True)

    return AssembledContext(
        snapshot=snapshot,
        conversation_tail=model_tail,
        estimated_chars=est,
        truncated_messages=truncated,
        notes=notes,
        excluded_message_ids=excluded_ids,
        active_message_ids=active_ids,
        summary_before_truncation=summary_before,
        summary_after_truncation=summary_text,
        summary_truncated=summary_truncated,
        diagnostics=diag,
    )


def validate_summary_does_not_override_structure(
    project: ProjectState,
    *,
    before_decisions: list[tuple[str, str]],
    before_stack: list[str],
    before_rejected: list[str],
) -> bool:
    """Post-condition helper for tests / callers."""
    after_decisions = [
        (d.title, d.choice)
        for d in project.decisions
        if getattr(d, "status", "accepted") != "superseded"
    ]
    after_stack = list(project.tech_stack)
    after_rejected = [r.approach for r in getattr(project, "rejected_approaches", []) or []]
    return (
        after_decisions == before_decisions
        and after_stack == before_stack
        and after_rejected == before_rejected
    )
