"""Track Grill outcomes: blocked findings, readiness passes, estimated tokens saved."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

# Rough heuristic: one blocked critical finding ≈ one avoided agent run ≈ N tokens.
TOKENS_PER_BLOCKED_FINDING = 25_000
TOKENS_PER_READINESS_PASS = 40_000


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return f"roi_{uuid4().hex[:16]}"


@dataclass
class RoiSnapshot:
    org_id: str
    findings_blocked: int
    readiness_passes: int
    agent_runs_before: int
    agent_runs_after: int
    estimated_tokens_saved: int
    readiness_pass_rate: float
    projects_scored: int


def record_event(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    event_type: str,
    project_id: str | None = None,
    user_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    eid = new_id()
    conn.execute(
        """
        INSERT INTO roi_events (
            id, org_id, project_id, user_id, event_type, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            eid,
            org_id,
            project_id,
            user_id,
            event_type,
            json.dumps(payload or {}),
            _utcnow(),
        ),
    )
    return eid


def report_agent_runs(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    project_id: str,
    user_id: str | None,
    runs_before: int,
    runs_after: int,
    notes: str | None = None,
) -> str:
    return record_event(
        conn,
        org_id=org_id,
        project_id=project_id,
        user_id=user_id,
        event_type="agent_runs_reported",
        payload={
            "runs_before": max(0, int(runs_before)),
            "runs_after": max(0, int(runs_after)),
            "notes": notes or "",
        },
    )


def compute_org_roi(conn: sqlite3.Connection, org_id: str) -> RoiSnapshot:
    rows = conn.execute(
        """
        SELECT event_type, payload_json FROM roi_events
        WHERE org_id = ?
        """,
        (org_id,),
    ).fetchall()

    blocked = 0
    passes = 0
    fails = 0
    before = 0
    after = 0
    projects: set[str] = set()

    for row in rows:
        et = row["event_type"]
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        pid = payload.get("project_id")
        if isinstance(pid, str):
            projects.add(pid)
        if et == "finding_blocked_from_impl":
            blocked += 1
        elif et == "readiness_pass":
            passes += 1
        elif et == "readiness_fail":
            fails += 1
        elif et == "agent_runs_reported":
            before += int(payload.get("runs_before") or 0)
            after += int(payload.get("runs_after") or 0)

    total_gate = passes + fails
    pass_rate = (passes / total_gate) if total_gate else 0.0
    tokens = (
        blocked * TOKENS_PER_BLOCKED_FINDING
        + passes * TOKENS_PER_READINESS_PASS
        + max(0, before - after) * TOKENS_PER_BLOCKED_FINDING
    )
    return RoiSnapshot(
        org_id=org_id,
        findings_blocked=blocked,
        readiness_passes=passes,
        agent_runs_before=before,
        agent_runs_after=after,
        estimated_tokens_saved=tokens,
        readiness_pass_rate=round(pass_rate, 4),
        projects_scored=len(projects),
    )


def snapshot_dict(snap: RoiSnapshot) -> dict[str, Any]:
    return {
        "org_id": snap.org_id,
        "findings_blocked_from_implementation": snap.findings_blocked,
        "readiness_gate_passes": snap.readiness_passes,
        "readiness_gate_pass_rate": snap.readiness_pass_rate,
        "agent_runs_before": snap.agent_runs_before,
        "agent_runs_after": snap.agent_runs_after,
        "estimated_tokens_saved": snap.estimated_tokens_saved,
        "projects_scored": snap.projects_scored,
        "assumptions": {
            "tokens_per_blocked_finding": TOKENS_PER_BLOCKED_FINDING,
            "tokens_per_readiness_pass": TOKENS_PER_READINESS_PASS,
            "note": "Estimates are heuristic for pricing conversations — not billed metering.",
        },
    }
