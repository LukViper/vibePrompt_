"""Database backend selection: SQLite (local-dev) or PostgreSQL (production)."""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal, Sequence
from urllib.parse import urlparse

DatabaseBackend = Literal["sqlite", "postgres"]

_PLACEHOLDER = re.compile(r"\?")


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


def adapt_sql(sql: str, backend: DatabaseBackend) -> str:
    """Translate SQLite-style ? placeholders to psycopg %s when needed."""
    if backend != "postgres":
        return sql
    return _PLACEHOLDER.sub("%s", sql)


def normalize_ddl(sql: str, backend: DatabaseBackend) -> str:
    """Strip SQLite-only DDL clauses so the same schema works on Postgres."""
    if backend != "postgres":
        return sql
    return sql.replace(" COLLATE NOCASE", "")


def is_integrity_error(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    try:
        from psycopg.errors import IntegrityError as PgIntegrityError

        if isinstance(exc, PgIntegrityError):
            return True
    except ImportError:
        pass
    return False


def is_operational_error(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.OperationalError):
        return True
    try:
        from psycopg import Error as PsycopgError

        if isinstance(exc, PsycopgError):
            msg = str(exc).lower()
            return "already exists" in msg or "duplicate column" in msg
    except ImportError:
        pass
    return False


class DbConn:
    """Thin adapter so repositories can share SQLite and Postgres SQL."""

    def __init__(self, raw: Any, backend: DatabaseBackend) -> None:
        self.raw = raw
        self.backend = backend

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        statement = adapt_sql(sql, self.backend)
        if params is None:
            return self.raw.execute(statement)
        return self.raw.execute(statement, tuple(params))

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()

    def __enter__(self) -> DbConn:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is not None:
                self.rollback()
            else:
                self.commit()
        finally:
            self.close()
        return False


def connect(backend: DatabaseBackend, target: str) -> DbConn:
    """Open a DB connection usable as a context manager (commit/close on exit)."""
    if backend == "sqlite":
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        raw.execute("PRAGMA busy_timeout = 30000")
        return DbConn(raw, "sqlite")

    if not postgres_available():
        raise RuntimeError(
            "psycopg is required for Postgres. pip install 'psycopg[binary]>=3.2'"
        )
    import psycopg
    from psycopg.rows import dict_row

    raw = psycopg.connect(target, row_factory=dict_row)
    return DbConn(raw, "postgres")


def list_tables(conn: DbConn) -> set[str]:
    if conn.backend == "sqlite":
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {_row_get(r, "name", 0) for r in rows}
    rows = conn.execute(
        "SELECT tablename AS name FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
    ).fetchall()
    return {_row_get(r, "name", 0) for r in rows}


def table_columns(conn: DbConn, table: str) -> set[str]:
    if table not in list_tables(conn):
        return set()
    if conn.backend == "sqlite":
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {_row_get(r, "name", 1) for r in rows}
    rows = conn.execute(
        """
        SELECT column_name AS name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ?
        """,
        (table,),
    ).fetchall()
    return {_row_get(r, "name", 0) for r in rows}


def _row_get(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except Exception:
        return row[index]


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
        with connect(backend, target) as conn:
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
