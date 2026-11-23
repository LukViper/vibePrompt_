"""Append-only audit log. Never hard-delete rows."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_audit(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    user_id: str | None = None,
    before: Any = None,
    after: Any = None,
) -> str:
    audit_id = f"aud_{uuid.uuid4().hex[:16]}"
    conn.execute(
        """
        INSERT INTO audit_logs (
            id, org_id, user_id, action, target_type, target_id,
            before_json, after_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            org_id,
            user_id,
            action,
            target_type,
            target_id,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
            _utcnow(),
        ),
    )
    return audit_id


def list_audit(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, org_id, user_id, action, target_type, target_id,
               before_json, after_json, created_at
        FROM audit_logs
        WHERE org_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (org_id, max(1, min(limit, 500))),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "org_id": r["org_id"],
                "user_id": r["user_id"],
                "action": r["action"],
                "target_type": r["target_type"],
                "target_id": r["target_id"],
                "before": json.loads(r["before_json"]) if r["before_json"] else None,
                "after": json.loads(r["after_json"]) if r["after_json"] else None,
                "created_at": r["created_at"],
            }
        )
    return out
