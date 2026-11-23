"""Database backend selection: SQLite (local-dev) or PostgreSQL (production)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Literal
from urllib.parse import urlparse

DatabaseBackend = Literal["sqlite", "postgres"]


def resolve_backend(
    *,
    database_backend: str,
    database_url: str,
    database_path: str,
) -> tuple[DatabaseBackend, str]:
    backend = (database_backend or "sqlite").strip().lower()
    url = (database_url or "").strip()
    if backend == "postgres" or url.startswith(("postgres://", "postgresql://")):
        if not url:
            raise RuntimeError(
                "DATABASE_BACKEND=postgres requires DATABASE_URL "
                "(e.g. Neon postgresql://...)"
            )
        # Neon / Heroku sometimes use postgres://
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        return "postgres", url
    return "sqlite", database_path


def assert_production_backend(
    *,
    is_production: bool,
    backend: DatabaseBackend,
) -> None:
    if is_production and backend == "sqlite":
        raise RuntimeError(
            "SQLite is local-dev only. Set DATABASE_URL to a managed Postgres "
            "(Neon/RDS/Supabase) when APP_ENV=production."
        )


@contextmanager
def connect_sqlite(path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def postgres_available() -> bool:
    try:
        import psycopg  # noqa: F401

        return True
    except ImportError:
        return False


@contextmanager
def connect_postgres(url: str) -> Iterator[Any]:
    if not postgres_available():
        raise RuntimeError(
            "psycopg is required for Postgres. pip install 'psycopg[binary]>=3.2'"
        )
    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(url, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ping(backend: DatabaseBackend, target: str) -> bool:
    try:
        if backend == "sqlite":
            with connect_sqlite(target) as conn:
                conn.execute("SELECT 1")
            return True
        with connect_postgres(target) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def redact_database_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        db = (parsed.path or "").lstrip("/")
        return f"{parsed.scheme}://***@{host}/{db}"
    except Exception:
        return "***"
