"""Organizations, memberships, and row-level tenant helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

OrgRole = Literal["admin", "member", "viewer"]
PlanTier = Literal["free", "pro", "team"]


@dataclass(frozen=True)
class OrgMembership:
    org_id: str
    user_id: str
    role: OrgRole


@dataclass(frozen=True)
class Organization:
    id: str
    name: str
    plan: PlanTier
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    mfa_required: bool = False


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def ensure_personal_org(
    conn: Any,
    *,
    user_id: str,
    email: str | None = None,
) -> str:
    """Create or return the user's personal organization (admin membership)."""
    row = conn.execute(
        """
        SELECT o.id FROM organizations o
        JOIN org_memberships m ON m.org_id = o.id
        WHERE m.user_id = ? AND o.kind = 'personal'
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if row:
        try:
            return row["id"]
        except Exception:
            return row[0]

    org_id = new_id("org")
    label = (email or user_id).split("@")[0][:64] or "Personal"
    now = _utcnow()
    conn.execute(
        """
        INSERT INTO organizations (id, name, kind, plan, created_at, updated_at)
        VALUES (?, ?, 'personal', 'free', ?, ?)
        """,
        (org_id, f"{label}'s workspace", now, now),
    )
    conn.execute(
        """
        INSERT INTO org_memberships (org_id, user_id, role, created_at)
        VALUES (?, ?, 'admin', ?)
        """,
        (org_id, user_id, now),
    )
    return org_id


def get_membership(
    conn: Any, *, org_id: str, user_id: str
) -> OrgMembership | None:
    row = conn.execute(
        """
        SELECT org_id, user_id, role FROM org_memberships
        WHERE org_id = ? AND user_id = ?
        """,
        (org_id, user_id),
    ).fetchone()
    if not row:
        return None
    return OrgMembership(
        org_id=row["org_id"],
        user_id=row["user_id"],
        role=row["role"],  # type: ignore[arg-type]
    )


def user_org_ids(conn: Any, user_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT org_id FROM org_memberships WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return [r["org_id"] for r in rows]


def get_org(conn: Any, org_id: str) -> Organization | None:
    row = conn.execute(
        """
        SELECT id, name, plan, stripe_customer_id, stripe_subscription_id,
               COALESCE(mfa_required, 0) AS mfa_required
        FROM organizations WHERE id = ?
        """,
        (org_id,),
    ).fetchone()
    if not row:
        return None
    return Organization(
        id=row["id"],
        name=row["name"],
        plan=row["plan"] or "free",  # type: ignore[arg-type]
        stripe_customer_id=row["stripe_customer_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
        mfa_required=bool(row["mfa_required"]),
    )


def role_can_resolve_findings(role: OrgRole) -> bool:
    return role in ("admin", "member")


def role_can_export_specs(role: OrgRole) -> bool:
    return role in ("admin", "member")


def role_can_admin_org(role: OrgRole) -> bool:
    return role == "admin"


def plan_allows_unlimited_reviews(plan: PlanTier) -> bool:
    return plan in ("pro", "team")


def plan_includes_audit_log(plan: PlanTier) -> bool:
    return plan == "team"
