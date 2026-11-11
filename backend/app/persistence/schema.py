"""SQLite schema bootstrap and lightweight migrations for auth/free-tier/BYOK."""

from __future__ import annotations

import sqlite3


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
)


PROJECT_OWNER_MIGRATION = (
    """
    ALTER TABLE projects ADD COLUMN owner_id TEXT
    """,
)


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    _ensure_project_owner_column(conn)
    _ensure_user_profile_columns(conn)
    conn.commit()


def _ensure_project_owner_column(conn: sqlite3.Connection) -> None:
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(projects)").fetchall()
    }
    if "projects" not in {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }:
        return
    if "owner_id" not in cols:
        try:
            conn.execute(PROJECT_OWNER_MIGRATION[0])
        except sqlite3.OperationalError:
            # Column already exists under a race, or projects table shape differs.
            pass


def _ensure_user_profile_columns(conn: sqlite3.Connection) -> None:
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "users" not in tables:
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    for col, ddl in (
        ("display_name", "ALTER TABLE users ADD COLUMN display_name TEXT"),
        ("avatar_url", "ALTER TABLE users ADD COLUMN avatar_url TEXT"),
        ("auth_provider", "ALTER TABLE users ADD COLUMN auth_provider TEXT DEFAULT 'legacy'"),
    ):
        if col not in cols:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
