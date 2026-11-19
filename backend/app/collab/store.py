"""Collaboration persistence helpers (comments, org library, notifications)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def add_finding_comment(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    project_id: str,
    finding_id: str,
    user_id: str,
    body: str,
    mention_user_ids: list[str] | None = None,
) -> dict[str, Any]:
    cid = new_id("cmt")
    now = _utcnow()
    mentions = mention_user_ids or []
    conn.execute(
        """
        INSERT INTO finding_comments (
            id, org_id, project_id, finding_id, user_id, body, mentions_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cid, org_id, project_id, finding_id, user_id, body.strip(), json.dumps(mentions), now),
    )
    for uid in mentions:
        nid = new_id("ntf")
        conn.execute(
            """
            INSERT INTO notifications (
                id, org_id, user_id, kind, title, body, payload_json, created_at, read_at
            ) VALUES (?, ?, ?, 'mention', ?, ?, ?, ?, NULL)
            """,
            (
                nid,
                org_id,
                uid,
                "You were mentioned on a finding",
                body.strip()[:280],
                json.dumps(
                    {
                        "project_id": project_id,
                        "finding_id": finding_id,
                        "comment_id": cid,
                    }
                ),
                now,
            ),
        )
    return {
        "id": cid,
        "org_id": org_id,
        "project_id": project_id,
        "finding_id": finding_id,
        "user_id": user_id,
        "body": body.strip(),
        "mentions": mentions,
        "created_at": now,
    }


def list_finding_comments(
    conn: sqlite3.Connection, *, project_id: str, finding_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, org_id, project_id, finding_id, user_id, body, mentions_json, created_at
        FROM finding_comments
        WHERE project_id = ? AND finding_id = ?
        ORDER BY created_at ASC
        """,
        (project_id, finding_id),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "org_id": r["org_id"],
                "project_id": r["project_id"],
                "finding_id": r["finding_id"],
                "user_id": r["user_id"],
                "body": r["body"],
                "mentions": json.loads(r["mentions_json"] or "[]"),
                "created_at": r["created_at"],
            }
        )
    return out


def upsert_org_rejected_approach(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    approach: str,
    reason: str,
    source_project_id: str | None,
    created_by: str | None,
) -> dict[str, Any]:
    rid = new_id("ora")
    now = _utcnow()
    existing = conn.execute(
        """
        SELECT id FROM org_rejected_approaches
        WHERE org_id = ? AND lower(approach) = lower(?)
        """,
        (org_id, approach.strip()),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE org_rejected_approaches
            SET reason = ?, source_project_id = COALESCE(?, source_project_id),
                updated_at = ?
            WHERE id = ?
            """,
            (reason.strip(), source_project_id, now, existing["id"]),
        )
        rid = existing["id"]
    else:
        conn.execute(
            """
            INSERT INTO org_rejected_approaches (
                id, org_id, approach, reason, source_project_id, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                org_id,
                approach.strip(),
                reason.strip(),
                source_project_id,
                created_by,
                now,
                now,
            ),
        )
    return {
        "id": rid,
        "org_id": org_id,
        "approach": approach.strip(),
        "reason": reason.strip(),
        "source_project_id": source_project_id,
        "created_by": created_by,
    }


def list_org_rejected_approaches(
    conn: sqlite3.Connection, *, org_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, org_id, approach, reason, source_project_id, created_by, created_at, updated_at
        FROM org_rejected_approaches
        WHERE org_id = ?
        ORDER BY updated_at DESC
        """,
        (org_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def notify_blocking_finding(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    project_id: str,
    finding_id: str,
    title: str,
    member_user_ids: list[str],
) -> int:
    now = _utcnow()
    n = 0
    for uid in member_user_ids:
        nid = new_id("ntf")
        conn.execute(
            """
            INSERT INTO notifications (
                id, org_id, user_id, kind, title, body, payload_json, created_at, read_at
            ) VALUES (?, ?, ?, 'blocking_finding', ?, ?, ?, ?, NULL)
            """,
            (
                nid,
                org_id,
                uid,
                "Blocking finding created",
                title[:280],
                json.dumps(
                    {
                        "project_id": project_id,
                        "finding_id": finding_id,
                    }
                ),
                now,
            ),
        )
        n += 1
    return n


def list_notifications(
    conn: sqlite3.Connection, *, user_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, org_id, user_id, kind, title, body, payload_json, created_at, read_at
        FROM notifications
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, max(1, min(limit, 200))),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "org_id": r["org_id"],
                "kind": r["kind"],
                "title": r["title"],
                "body": r["body"],
                "payload": json.loads(r["payload_json"] or "{}"),
                "created_at": r["created_at"],
                "read_at": r["read_at"],
            }
        )
    return out
