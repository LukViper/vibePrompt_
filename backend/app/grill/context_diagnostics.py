"""Per-request context diagnostics for summary truncation / stale-recommendation investigations.

Never logs API keys, passwords, tokens, or other secrets.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger("vibeprompt.context_diagnostics")

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|password|secret|token|authorization|bearer)\s*[:=]\s*\S+"
)


def _redact(text: str, *, max_len: int = 2000) -> str:
    cleaned = _SECRET_RE.sub(r"\1=[REDACTED]", text or "")
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned


@dataclass
class ContextDiagnostics:
    """One request's context assembly audit trail."""

    request_id: str
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    user_message: str = ""
    active_message_ids: list[str] = field(default_factory=list)
    active_messages: list[dict[str, str]] = field(default_factory=list)
    summary_before_truncation: str = ""
    summary_after_truncation: str = ""
    summary_truncated: bool = False
    summary_version: int | None = None
    summary_reused: bool = False
    excluded_message_ids: list[str] = field(default_factory=list)
    truncated_message_count: int = 0
    project_facts: list[dict[str, Any]] = field(default_factory=list)
    turn_exclusions: list[str] = field(default_factory=list)
    primary_snapshot_keys: list[str] = field(default_factory=list)
    primary_summary_excerpt: str = ""
    critic_snapshot_keys: list[str] = field(default_factory=list)
    critic_summary_excerpt: str = ""
    primary_critic_snapshots_identical: bool | None = None
    reply_before_postprocess: str = ""
    reply_after_postprocess: str = ""
    assembly_notes: list[str] = field(default_factory=list)
    estimated_chars: int = 0

    def to_safe_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["user_message"] = _redact(self.user_message, max_len=500)
        raw["summary_before_truncation"] = _redact(self.summary_before_truncation)
        raw["summary_after_truncation"] = _redact(self.summary_after_truncation)
        raw["primary_summary_excerpt"] = _redact(self.primary_summary_excerpt, max_len=800)
        raw["critic_summary_excerpt"] = _redact(self.critic_summary_excerpt, max_len=800)
        raw["reply_before_postprocess"] = _redact(self.reply_before_postprocess, max_len=800)
        raw["reply_after_postprocess"] = _redact(self.reply_after_postprocess, max_len=800)
        safe_msgs = []
        for m in self.active_messages:
            safe_msgs.append(
                {
                    "id": m.get("id", ""),
                    "role": m.get("role", ""),
                    "content": _redact(m.get("content", ""), max_len=240),
                }
            )
        raw["active_messages"] = safe_msgs
        return raw

    def emit(self) -> None:
        _log.info("context_diagnostics %s", json.dumps(self.to_safe_dict(), default=str))


# In-memory ring for tests / recent requests (no secrets)
_RECENT: list[ContextDiagnostics] = []
_MAX_RECENT = 50


def record_diagnostics(diag: ContextDiagnostics, *, emit: bool = True) -> None:
    _RECENT.append(diag)
    if len(_RECENT) > _MAX_RECENT:
        del _RECENT[: len(_RECENT) - _MAX_RECENT]
    if emit:
        diag.emit()


def recent_diagnostics(limit: int = 10) -> list[ContextDiagnostics]:
    return list(_RECENT[-limit:])


def clear_diagnostics() -> None:
    _RECENT.clear()


def snapshot_excerpt(snapshot: dict[str, Any] | None) -> tuple[list[str], str]:
    if not snapshot:
        return [], ""
    keys = sorted(snapshot.keys())
    summary = ""
    cs = snapshot.get("conversation_summary")
    if isinstance(cs, dict):
        summary = str(cs.get("text") or "")[:800]
    elif isinstance(cs, str):
        summary = cs[:800]
    return keys, summary
