"""Schema bootstrap and lightweight migrations for auth/free-tier/BYOK."""

from __future__ import annotations

from typing import Any

from app.persistence.db import (
    DbConn,
    is_operational_error,
    list_tables,
    normalize_ddl,
    table_columns,
)


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(email)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS free_tier_allocations (
        user_id TEXT PRIMARY KEY,
        generations_allocated INTEGER NOT NULL,
        generations_used INTEGER NOT NULL DEFAULT 0,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generation_usage (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER,
        output_tokens INTEGER,
        total_tokens INTEGER,
        status TEXT NOT NULL,
        funding_source TEXT NOT NULL,
        error_message TEXT,
        idempotency_key TEXT,
        created_at TEXT NOT NULL,
        completed_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_generation_usage_idempotency
    ON generation_usage(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_generation_usage_user_created
    ON generation_usage(user_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS user_provider_configs (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        encrypted_api_key TEXT NOT NULL,
        base_url TEXT,
        is_active INTEGER NOT NULL DEFAULT 0,
        validated_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(user_id, provider),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_provider_active
    ON user_provider_configs(user_id, is_active)
    """,
    """
    CREATE TABLE IF NOT EXISTS rate_limit_buckets (
        bucket_key TEXT PRIMARY KEY,
        window_start TEXT NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guest_sessions (
        id TEXT PRIMARY KEY,
        ip_hash TEXT,
        generations_allocated INTEGER NOT NULL,
        generations_used INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        day_key TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_guest_sessions_ip_day
    ON guest_sessions(ip_hash, day_key)
    """,
    """
    CREATE TABLE IF NOT EXISTS global_usage_counters (
        counter_key TEXT PRIMARY KEY,
        window_start TEXT NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS organizations (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'personal',
        plan TEXT NOT NULL DEFAULT 'free',
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        mfa_required INTEGER NOT NULL DEFAULT 0,
        saml_enabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS org_memberships (
        org_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'member',
        created_at TEXT NOT NULL,
        PRIMARY KEY (org_id, user_id),
        FOREIGN KEY(org_id) REFERENCES organizations(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_org_memberships_user
    ON org_memberships(user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        user_id TEXT,
        action TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT,
        before_json TEXT,
        after_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(org_id) REFERENCES organizations(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_logs_org_created
    ON audit_logs(org_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS user_mfa (
        user_id TEXT PRIMARY KEY,
        totp_secret TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS roi_events (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        project_id TEXT,
        user_id TEXT,
        event_type TEXT NOT NULL,
        payload_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(org_id) REFERENCES organizations(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_roi_events_org
    ON roi_events(org_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS finding_comments (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        finding_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        body TEXT NOT NULL,
        mentions_json TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_finding_comments_finding
    ON finding_comments(project_id, finding_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS org_rejected_approaches (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        approach TEXT NOT NULL,
        reason TEXT NOT NULL,
        source_project_id TEXT,
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_org_rejected_org
    ON org_rejected_approaches(org_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT,
        payload_json TEXT,
        created_at TEXT NOT NULL,
        read_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_notifications_user
    ON notifications(user_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS org_playbooks (
        id TEXT PRIMARY KEY,
        org_id TEXT NOT NULL,
        title TEXT NOT NULL,
        vertical TEXT,
        content_text TEXT NOT NULL,
        skill_id TEXT,
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
)


PROJECT_OWNER_MIGRATION = (
    """
    ALTER TABLE projects ADD COLUMN owner_id TEXT
    """,
)


def apply_schema(conn: DbConn | Any) -> None:
    backend = getattr(conn, "backend", "sqlite")
    if backend == "sqlite" and hasattr(conn, "execute"):
        # Native sqlite path still used by KnowledgeStore callers.
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except Exception:
            pass
    for statement in SCHEMA_STATEMENTS:
        ddl = normalize_ddl(statement, backend) if backend in ("sqlite", "postgres") else statement
        if hasattr(conn, "backend"):
            conn.execute(ddl)
        else:
            conn.execute(ddl)
    _ensure_project_owner_column(conn)
    _ensure_project_tenancy_columns(conn)
    _ensure_usage_cost_columns(conn)
    _ensure_user_profile_columns(conn)
    _ensure_user_org_columns(conn)
    _ensure_guest_password_hash_nullable(conn)
    if hasattr(conn, "commit"):
        conn.commit()


def _ensure_guest_password_hash_nullable(conn: DbConn | Any) -> None:
    """Legacy users.password_hash was NOT NULL; guests store NULL. Recreate if needed."""
    tables = list_tables(conn) if isinstance(conn, DbConn) else _sqlite_tables(conn)
    if "users" not in tables:
        return
    # SQLite cannot ALTER COLUMN nullability; empty-string sentinel is fine for guests
    # when the column remains NOT NULL on older DBs. create_guest_session uses ''.
    pass


def _sqlite_tables(conn: Any) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _cols(conn: DbConn | Any, table: str) -> set[str]:
    if isinstance(conn, DbConn):
        return table_columns(conn, table)
    tables = _sqlite_tables(conn)
    if table not in tables:
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_project_owner_column(conn: DbConn | Any) -> None:
    tables = list_tables(conn) if isinstance(conn, DbConn) else _sqlite_tables(conn)
    if "projects" not in tables:
        return
    cols = _cols(conn, "projects")
    if "owner_id" not in cols:
        try:
            conn.execute(PROJECT_OWNER_MIGRATION[0])
        except Exception as exc:
            if not is_operational_error(exc):
                raise


def _ensure_user_profile_columns(conn: DbConn | Any) -> None:
    tables = list_tables(conn) if isinstance(conn, DbConn) else _sqlite_tables(conn)
    if "users" not in tables:
        return
    cols = _cols(conn, "users")
    for col, ddl in (
        ("display_name", "ALTER TABLE users ADD COLUMN display_name TEXT"),
        ("avatar_url", "ALTER TABLE users ADD COLUMN avatar_url TEXT"),
        ("auth_provider", "ALTER TABLE users ADD COLUMN auth_provider TEXT DEFAULT 'legacy'"),
    ):
        if col not in cols:
            try:
                conn.execute(ddl)
            except Exception as exc:
                if not is_operational_error(exc):
                    raise


def _ensure_project_tenancy_columns(conn: DbConn | Any) -> None:
    cols = _cols(conn, "projects")
    if not cols:
        return
    for col, ddl in (
        ("org_id", "ALTER TABLE projects ADD COLUMN org_id TEXT"),
        ("deleted_at", "ALTER TABLE projects ADD COLUMN deleted_at TEXT"),
    ):
        if col not in cols:
            try:
                conn.execute(ddl)
            except Exception as exc:
                if not is_operational_error(exc):
                    raise


def _ensure_usage_cost_columns(conn: DbConn | Any) -> None:
    cols = _cols(conn, "generation_usage")
    if not cols:
        return
    for col, ddl in (
        ("org_id", "ALTER TABLE generation_usage ADD COLUMN org_id TEXT"),
        ("project_id", "ALTER TABLE generation_usage ADD COLUMN project_id TEXT"),
        ("latency_ms", "ALTER TABLE generation_usage ADD COLUMN latency_ms INTEGER"),
        ("cost_usd_estimate", "ALTER TABLE generation_usage ADD COLUMN cost_usd_estimate REAL"),
        ("trace_id", "ALTER TABLE generation_usage ADD COLUMN trace_id TEXT"),
    ):
        if col not in cols:
            try:
                conn.execute(ddl)
            except Exception as exc:
                if not is_operational_error(exc):
                    raise


def _ensure_user_org_columns(conn: DbConn | Any) -> None:
    cols = _cols(conn, "users")
    if not cols:
        return
    for col, ddl in (
        ("default_org_id", "ALTER TABLE users ADD COLUMN default_org_id TEXT"),
        ("mfa_enabled", "ALTER TABLE users ADD COLUMN mfa_enabled INTEGER DEFAULT 0"),
    ):
        if col not in cols:
            try:
                conn.execute(ddl)
            except Exception as exc:
                if not is_operational_error(exc):
                    raise
