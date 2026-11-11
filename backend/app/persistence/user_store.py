"""SQLite persistence for users, free-tier allocations, usage, and BYOK configs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from app.auth.models import UserPublic, UserRecord
from app.free_tier.models import (
    ByokConfigPublic,
    FundingSource,
    GenerationStatus,
)
from app.persistence.schema import apply_schema
from app.projects.models import utcnow


def new_id(prefix: str = "") -> str:
    raw = uuid4().hex
    return f"{prefix}{raw}" if prefix else raw


def _iso(dt: datetime | None = None) -> str:
    value = dt or utcnow()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class UserStore:
    """Concurrency-safe SQLite store for auth, free tier, usage, and BYOK."""

    def __init__(self, database_path: str) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            # Ensure projects table exists for owner_id migration compatibility.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            apply_schema(conn)

    # ------------------------------------------------------------------ users
    def create_user(self, *, email: str, password_hash: str) -> UserRecord:
        """Legacy local registration — stores a bcrypt hash. Prefer Supabase Auth in production."""
        user_id = new_id("usr_")
        created = utcnow()
        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO users (
                        id, email, password_hash, display_name, avatar_url,
                        auth_provider, created_at
                    ) VALUES (?, ?, ?, NULL, NULL, 'legacy', ?)
                    """,
                    (user_id, email.strip().lower(), password_hash, _iso(created)),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("Email already registered") from exc
        return UserRecord(
            id=user_id,
            email=email.strip().lower(),
            password_hash=password_hash,
            auth_provider="legacy",
            created_at=created,
        )

    def upsert_supabase_user(
        self,
        *,
        user_id: str,
        email: str | None,
        display_name: str | None = None,
        avatar_url: str | None = None,
        auth_provider: str = "supabase",
    ) -> UserRecord:
        """Create or refresh a local profile keyed by the verified Supabase user id.

        Never stores a password — credentials live in Supabase Auth only.
        """
        created = utcnow()
        email_norm = (email or f"{user_id}@users.supabase").strip().lower()
        provider = (auth_provider or "supabase").strip().lower()[:40]
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE users SET
                        email = COALESCE(?, email),
                        display_name = COALESCE(?, display_name),
                        avatar_url = COALESCE(?, avatar_url),
                        auth_provider = COALESCE(?, auth_provider),
                        password_hash = NULL
                    WHERE id = ?
                    """,
                    (
                        email_norm if email else None,
                        display_name,
                        avatar_url,
                        provider,
                        user_id,
                    ),
                )
                conn.commit()
            else:
                # Email may already exist from a legacy account — re-key to Supabase id when safe.
                by_email = conn.execute(
                    "SELECT * FROM users WHERE email = ?", (email_norm,)
                ).fetchone()
                if by_email and by_email["id"] != user_id:
                    # Keep distinct identities; use a synthetic unique email marker if needed.
                    if by_email["auth_provider"] == "legacy" and not by_email["password_hash"]:
                        pass
                    email_norm = f"{user_id[:8]}.{email_norm}"
                try:
                    conn.execute(
                        """
                        INSERT INTO users (
                            id, email, password_hash, display_name, avatar_url,
                            auth_provider, created_at
                        ) VALUES (?, ?, NULL, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            email_norm,
                            display_name,
                            avatar_url,
                            provider,
                            _iso(created),
                        ),
                    )
                    conn.commit()
                except sqlite3.IntegrityError as exc:
                    raise ValueError("Unable to create profile for authenticated user") from exc
        user = self.get_user(user_id)
        if user is None:
            raise ValueError("Failed to load profile after upsert")
        return user

    def get_user_by_email(self, email: str) -> UserRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def get_user(self, user_id: str) -> UserRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return self._row_to_user(row) if row else None

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> UserRecord:
        keys = row.keys()
        return UserRecord(
            id=row["id"],
            email=row["email"],
            password_hash=row["password_hash"],
            display_name=row["display_name"] if "display_name" in keys else None,
            avatar_url=row["avatar_url"] if "avatar_url" in keys else None,
            auth_provider=(
                row["auth_provider"] if "auth_provider" in keys and row["auth_provider"] else "legacy"
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def to_public(self, user: UserRecord) -> UserPublic:
        return UserPublic(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            auth_provider=user.auth_provider,
            created_at=user.created_at,
        )

    # ------------------------------------------------------------- free tier
    def ensure_free_tier_allocation(
        self,
        user_id: str,
        *,
        generations: int,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        """Idempotent one-time allocation. Concurrent calls cannot double-allocate."""
        now = _iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO free_tier_allocations (
                    user_id, generations_allocated, generations_used,
                    provider, model, created_at, updated_at
                ) VALUES (?, ?, 0, ?, ?, ?, ?)
                """,
                (user_id, generations, provider, model, now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM free_tier_allocations WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        assert row is not None
        return dict(row)

    def get_free_tier_allocation(self, user_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM free_tier_allocations WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def reserve_platform_generation(
        self,
        user_id: str,
        *,
        provider: str,
        model: str,
        idempotency_key: str | None = None,
    ) -> str:
        """
        Atomically consume one free generation slot and create a pending usage row.
        Raises ValueError if exhausted or duplicate idempotency key already succeeded.
        """
        generation_id = new_id("gen_")
        now = _iso()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if idempotency_key:
                    existing = conn.execute(
                        """
                        SELECT id, status FROM generation_usage
                        WHERE user_id = ? AND idempotency_key = ?
                        """,
                        (user_id, idempotency_key),
                    ).fetchone()
                    if existing:
                        if existing["status"] == GenerationStatus.SUCCESS.value:
                            conn.execute("COMMIT")
                            raise LookupError(existing["id"])
                        if existing["status"] == GenerationStatus.PENDING.value:
                            conn.execute("COMMIT")
                            return existing["id"]

                cur = conn.execute(
                    """
                    UPDATE free_tier_allocations
                    SET generations_used = generations_used + 1,
                        updated_at = ?
                    WHERE user_id = ?
                      AND generations_used < generations_allocated
                    """,
                    (now, user_id),
                )
                if cur.rowcount != 1:
                    raise ValueError("Free generations exhausted")

                conn.execute(
                    """
                    INSERT INTO generation_usage (
                        id, user_id, provider, model,
                        input_tokens, output_tokens, total_tokens,
                        status, funding_source, error_message,
                        idempotency_key, created_at, completed_at
                    ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?, NULL, ?, ?, NULL)
                    """,
                    (
                        generation_id,
                        user_id,
                        provider,
                        model,
                        GenerationStatus.PENDING.value,
                        FundingSource.PLATFORM.value,
                        idempotency_key,
                        now,
                    ),
                )
                conn.execute("COMMIT")
            except LookupError:
                raise
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
        return generation_id

    def complete_generation(
        self,
        generation_id: str,
        *,
        success: bool,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        error_message: str | None = None,
        release_reservation: bool = False,
    ) -> None:
        now = _iso()
        status = (
            GenerationStatus.SUCCESS.value
            if success
            else (
                GenerationStatus.RELEASED.value
                if release_reservation
                else GenerationStatus.FAILED.value
            )
        )
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM generation_usage WHERE id = ?",
                    (generation_id,),
                ).fetchone()
                if not row:
                    conn.execute("ROLLBACK")
                    raise KeyError(f"Generation {generation_id} not found")

                if row["status"] == GenerationStatus.SUCCESS.value:
                    conn.execute("COMMIT")
                    return

                conn.execute(
                    """
                    UPDATE generation_usage
                    SET status = ?,
                        input_tokens = ?,
                        output_tokens = ?,
                        total_tokens = ?,
                        error_message = ?,
                        completed_at = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        input_tokens,
                        output_tokens,
                        total_tokens,
                        (error_message or "")[:500] if error_message else None,
                        now,
                        generation_id,
                    ),
                )

                # Failed / released platform generations must not consume allowance.
                if (
                    row["funding_source"] == FundingSource.PLATFORM.value
                    and row["status"] == GenerationStatus.PENDING.value
                    and not success
                ):
                    conn.execute(
                        """
                        UPDATE free_tier_allocations
                        SET generations_used = MAX(generations_used - 1, 0),
                            updated_at = ?
                        WHERE user_id = ?
                        """,
                        (now, row["user_id"]),
                    )
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    def record_byok_generation(
        self,
        user_id: str,
        *,
        provider: str,
        model: str,
        success: bool,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        error_message: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        generation_id = new_id("gen_")
        now = _iso()
        status = (
            GenerationStatus.SUCCESS.value
            if success
            else GenerationStatus.FAILED.value
        )
        with self._lock, self._connect() as conn:
            if idempotency_key:
                existing = conn.execute(
                    """
                    SELECT id FROM generation_usage
                    WHERE user_id = ? AND idempotency_key = ?
                    """,
                    (user_id, idempotency_key),
                ).fetchone()
                if existing:
                    return existing["id"]
            conn.execute(
                """
                INSERT INTO generation_usage (
                    id, user_id, provider, model,
                    input_tokens, output_tokens, total_tokens,
                    status, funding_source, error_message,
                    idempotency_key, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generation_id,
                    user_id,
                    provider,
                    model,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    status,
                    FundingSource.BYOK.value,
                    (error_message or "")[:500] if error_message else None,
                    idempotency_key,
                    now,
                    now,
                ),
            )
            conn.commit()
        return generation_id

    # ------------------------------------------------------------------- BYOK
    def upsert_provider_config(
        self,
        user_id: str,
        *,
        provider: str,
        model: str,
        encrypted_api_key: str,
        base_url: str | None,
        set_active: bool,
    ) -> ByokConfigPublic:
        config_id = new_id("cfg_")
        now = _iso()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    """
                    SELECT id FROM user_provider_configs
                    WHERE user_id = ? AND provider = ?
                    """,
                    (user_id, provider),
                ).fetchone()
                if set_active:
                    conn.execute(
                        """
                        UPDATE user_provider_configs
                        SET is_active = 0, updated_at = ?
                        WHERE user_id = ?
                        """,
                        (now, user_id),
                    )
                if existing:
                    conn.execute(
                        """
                        UPDATE user_provider_configs
                        SET model = ?,
                            encrypted_api_key = ?,
                            base_url = ?,
                            is_active = ?,
                            validated_at = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            model,
                            encrypted_api_key,
                            base_url,
                            1 if set_active else 0,
                            now,
                            now,
                            existing["id"],
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO user_provider_configs (
                            id, user_id, provider, model, encrypted_api_key,
                            base_url, is_active, validated_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            config_id,
                            user_id,
                            provider,
                            model,
                            encrypted_api_key,
                            base_url,
                            1 if set_active else 0,
                            now,
                            now,
                            now,
                        ),
                    )
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
        return ByokConfigPublic(
            provider=provider,
            model=model,
            base_url=base_url,
            is_active=set_active,
            validated_at=utcnow(),
            has_api_key=True,
        )

    def list_provider_configs(self, user_id: str) -> list[ByokConfigPublic]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT provider, model, base_url, is_active, validated_at
                FROM user_provider_configs
                WHERE user_id = ?
                ORDER BY provider
                """,
                (user_id,),
            ).fetchall()
        result: list[ByokConfigPublic] = []
        for row in rows:
            result.append(
                ByokConfigPublic(
                    provider=row["provider"],
                    model=row["model"],
                    base_url=row["base_url"],
                    is_active=bool(row["is_active"]),
                    validated_at=(
                        datetime.fromisoformat(row["validated_at"])
                        if row["validated_at"]
                        else None
                    ),
                    has_api_key=True,
                )
            )
        return result

    def get_active_provider_config(self, user_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM user_provider_configs
                WHERE user_id = ? AND is_active = 1
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_provider_config(
        self, user_id: str, provider: str
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM user_provider_configs
                WHERE user_id = ? AND provider = ?
                """,
                (user_id, provider),
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------- rate limit
    def check_and_increment_rate_limit(
        self,
        bucket_key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """Return (allowed, remaining). Uses fixed windows."""
        now = utcnow()
        window_start = datetime.fromtimestamp(
            (int(now.timestamp()) // window_seconds) * window_seconds,
            tz=timezone.utc,
        )
        window_iso = _iso(window_start)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM rate_limit_buckets WHERE bucket_key = ?",
                    (bucket_key,),
                ).fetchone()
                if not row or row["window_start"] != window_iso:
                    conn.execute(
                        """
                        INSERT INTO rate_limit_buckets (bucket_key, window_start, request_count)
                        VALUES (?, ?, 1)
                        ON CONFLICT(bucket_key) DO UPDATE SET
                            window_start = excluded.window_start,
                            request_count = 1
                        """,
                        (bucket_key, window_iso),
                    )
                    conn.execute("COMMIT")
                    return True, max(limit - 1, 0)

                if row["request_count"] >= limit:
                    conn.execute("COMMIT")
                    return False, 0

                conn.execute(
                    """
                    UPDATE rate_limit_buckets
                    SET request_count = request_count + 1
                    WHERE bucket_key = ?
                    """,
                    (bucket_key,),
                )
                remaining = max(limit - (row["request_count"] + 1), 0)
                conn.execute("COMMIT")
                return True, remaining
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    # ----------------------------------------------------------- project owner
    def set_project_owner(self, project_id: str, owner_id: str) -> None:
        with self._lock, self._connect() as conn:
            cols = {
                r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()
            }
            if "owner_id" not in cols:
                return
            conn.execute(
                "UPDATE projects SET owner_id = ? WHERE id = ?",
                (owner_id, project_id),
            )
            conn.commit()

    def get_project_owner(self, project_id: str) -> str | None:
        with self._lock, self._connect() as conn:
            cols = {
                r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()
            }
            if "owner_id" not in cols:
                return None
            row = conn.execute(
                "SELECT owner_id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        return row["owner_id"]
