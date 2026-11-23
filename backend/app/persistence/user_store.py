"""User / free-tier / BYOK persistence (SQLite locally, Postgres in production)."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Mapping
from uuid import uuid4

from app.auth.models import UserPublic, UserRecord
from app.free_tier.models import (
    ByokConfigPublic,
    FundingSource,
    GenerationStatus,
)
from app.persistence.db import (
    DatabaseBackend,
    DbConn,
    connect,
    is_integrity_error,
    table_columns,
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
    """Concurrency-safe auth/free-tier/BYOK store (SQLite or Postgres)."""

    def __init__(
        self,
        database_path: str | None = None,
        *,
        backend: DatabaseBackend | None = None,
        target: str | None = None,
    ) -> None:
        if backend and target:
            self.backend: DatabaseBackend = backend
            self.target = target
        elif database_path:
            self.backend = "sqlite"
            self.target = database_path
        else:
            raise ValueError("UserStore requires database_path or backend+target")
        self.path = self.target  # backwards-compatible attribute for tests
        self._lock = Lock()
        self._init_db()

    def _connect(self) -> DbConn:
        return connect(self.backend, self.target)

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
            except Exception as exc:
                if not is_integrity_error(exc):
                    raise
                raise ValueError("Email already registered") from exc
            from app.persistence.tenancy import ensure_personal_org

            org_id = ensure_personal_org(
                conn, user_id=user_id, email=email.strip().lower()
            )
            conn.execute(
                "UPDATE users SET default_org_id = ? WHERE id = ?",
                (org_id, user_id),
            )
            conn.commit()
        return UserRecord(
            id=user_id,
            email=email.strip().lower(),
            password_hash=password_hash,
            auth_provider="legacy",
            created_at=created,
        )

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        """Replace the legacy password hash for an existing user."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE users
                SET password_hash = ?
                WHERE id = ? AND COALESCE(auth_provider, 'legacy') IN ('legacy', '')
                """,
                (password_hash, user_id),
            )
            if cur.rowcount == 0:
                raise ValueError("User not found or not a legacy password account")
            conn.commit()

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
                except Exception as exc:
                    if not is_integrity_error(exc):
                        raise
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
    def _row_to_user(row: Mapping[str, Any]) -> UserRecord:
        keys = set(row.keys())
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
            conn.begin_write()
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
                except Exception:
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
            conn.begin_write()
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
                except Exception:
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
            conn.begin_write()
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
                except Exception:
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
            conn.begin_write()
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
                except Exception:
                    pass
                raise

    def check_and_increment_global_counter(
        self,
        counter_key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """Global circuit breaker (e.g. shared QWEN_API_KEY daily cap)."""
        now = utcnow()
        window_start = datetime.fromtimestamp(
            (int(now.timestamp()) // window_seconds) * window_seconds,
            tz=timezone.utc,
        )
        window_iso = _iso(window_start)
        with self._lock, self._connect() as conn:
            conn.begin_write()
            try:
                row = conn.execute(
                    "SELECT * FROM global_usage_counters WHERE counter_key = ?",
                    (counter_key,),
                ).fetchone()
                if not row or row["window_start"] != window_iso:
                    conn.execute(
                        """
                        INSERT INTO global_usage_counters (counter_key, window_start, request_count)
                        VALUES (?, ?, 1)
                        ON CONFLICT(counter_key) DO UPDATE SET
                            window_start = excluded.window_start,
                            request_count = 1
                        """,
                        (counter_key, window_iso),
                    )
                    conn.execute("COMMIT")
                    return True, max(limit - 1, 0)
                if row["request_count"] >= limit:
                    conn.execute("COMMIT")
                    return False, 0
                conn.execute(
                    """
                    UPDATE global_usage_counters
                    SET request_count = request_count + 1
                    WHERE counter_key = ?
                    """,
                    (counter_key,),
                )
                remaining = max(limit - (row["request_count"] + 1), 0)
                conn.execute("COMMIT")
                return True, remaining
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    # --------------------------------------------------------------- guests
    def create_guest_session(
        self,
        *,
        ip_hash: str | None,
        generations: int,
        expires_minutes: int,
        provider: str,
        model: str,
    ) -> tuple[UserRecord, dict[str, Any]]:
        """
        Mint a synthetic guest user + capped free-tier allocation.
        Returns (user, session_row).
        """
        guest_id = new_id("gst_")
        created = utcnow()
        expires = created.timestamp() + expires_minutes * 60
        expires_at = datetime.fromtimestamp(expires, tz=timezone.utc)
        day_key = created.strftime("%Y-%m-%d")
        email = f"{guest_id}@guest.local"
        with self._lock, self._connect() as conn:
            conn.begin_write()
            try:
                conn.execute(
                    """
                    INSERT INTO users (
                        id, email, password_hash, display_name, avatar_url,
                        auth_provider, created_at
                    ) VALUES (?, ?, '', 'Guest', NULL, 'guest', ?)
                    """,
                    (guest_id, email, _iso(created)),
                )
                conn.execute(
                    """
                    INSERT INTO guest_sessions (
                        id, ip_hash, generations_allocated, generations_used,
                        created_at, expires_at, day_key
                    ) VALUES (?, ?, ?, 0, ?, ?, ?)
                    """,
                    (
                        guest_id,
                        ip_hash or "",
                        generations,
                        _iso(created),
                        _iso(expires_at),
                        day_key,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO free_tier_allocations (
                        user_id, generations_allocated, generations_used,
                        provider, model, created_at, updated_at
                    ) VALUES (?, ?, 0, ?, ?, ?, ?)
                    """,
                    (
                        guest_id,
                        generations,
                        provider,
                        model,
                        _iso(created),
                        _iso(created),
                    ),
                )
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        user = UserRecord(
            id=guest_id,
            email=email,
            password_hash="",
            display_name="Guest",
            auth_provider="guest",
            created_at=created,
        )
        session = {
            "id": guest_id,
            "ip_hash": ip_hash or "",
            "generations_allocated": generations,
            "generations_used": 0,
            "created_at": _iso(created),
            "expires_at": _iso(expires_at),
            "day_key": day_key,
        }
        return user, session

    def get_guest_session(self, guest_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM guest_sessions WHERE id = ?",
                (guest_id,),
            ).fetchone()
        return dict(row) if row else None

    def guest_session_expired(self, guest_id: str) -> bool:
        row = self.get_guest_session(guest_id)
        if not row:
            return True
        try:
            exp = datetime.fromisoformat(row["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            return utcnow() >= exp
        except (TypeError, ValueError):
            return True

    # ----------------------------------------------------------- project owner
    def set_project_owner(self, project_id: str, owner_id: str) -> None:
        with self._lock, self._connect() as conn:
            cols = table_columns(conn, "projects")
            if "owner_id" not in cols:
                return
            conn.execute(
                "UPDATE projects SET owner_id = ? WHERE id = ?",
                (owner_id, project_id),
            )
            conn.commit()

    def get_project_owner(self, project_id: str) -> str | None:
        with self._lock, self._connect() as conn:
            cols = table_columns(conn, "projects")
            if "owner_id" not in cols:
                return None
            row = conn.execute(
                "SELECT owner_id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        return row["owner_id"]

    # ----------------------------------------------------------- org / tenancy
    def ensure_user_org(self, user_id: str, email: str | None = None) -> str:
        from app.persistence.tenancy import ensure_personal_org

        with self._lock, self._connect() as conn:
            org_id = ensure_personal_org(conn, user_id=user_id, email=email)
            conn.execute(
                "UPDATE users SET default_org_id = COALESCE(default_org_id, ?) WHERE id = ?",
                (org_id, user_id),
            )
            conn.commit()
            return org_id

    def get_default_org_id(self, user_id: str) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT default_org_id FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if not row:
            return None
        return row["default_org_id"]

    def get_org_plan(self, org_id: str) -> str:
        from app.persistence.tenancy import get_org

        with self._lock, self._connect() as conn:
            org = get_org(conn, org_id)
        return (org.plan if org else "free") or "free"

    def set_org_plan(
        self,
        org_id: str,
        plan: str,
        *,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE organizations SET
                    plan = ?,
                    stripe_customer_id = COALESCE(?, stripe_customer_id),
                    stripe_subscription_id = COALESCE(?, stripe_subscription_id),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    plan,
                    stripe_customer_id,
                    stripe_subscription_id,
                    _iso(),
                    org_id,
                ),
            )
            conn.commit()

    def get_membership_role(self, org_id: str, user_id: str) -> str | None:
        from app.persistence.tenancy import get_membership

        with self._lock, self._connect() as conn:
            m = get_membership(conn, org_id=org_id, user_id=user_id)
        return m.role if m else None

    def emit_audit(
        self,
        *,
        org_id: str,
        action: str,
        target_type: str,
        target_id: str | None = None,
        user_id: str | None = None,
        before: Any = None,
        after: Any = None,
    ) -> str:
        from app.persistence.audit import emit_audit

        with self._lock, self._connect() as conn:
            audit_id = emit_audit(
                conn,
                org_id=org_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                user_id=user_id,
                before=before,
                after=after,
            )
            conn.commit()
            return audit_id

    def list_audit(self, org_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        from app.persistence.audit import list_audit

        with self._lock, self._connect() as conn:
            return list_audit(conn, org_id=org_id, limit=limit)

    def org_allows_unlimited(self, org_id: str | None) -> bool:
        if not org_id:
            return False
        from app.persistence.tenancy import plan_allows_unlimited_reviews

        plan = self.get_org_plan(org_id)  # type: ignore[arg-type]
        return plan_allows_unlimited_reviews(plan)  # type: ignore[arg-type]

    def admin_usage_metrics(self, *, limit: int = 50) -> dict[str, Any]:
        """Cost / latency aggregates for admin dashboard (API-first)."""
        with self._lock, self._connect() as conn:
            cols = table_columns(conn, "generation_usage")
            cost_col = "cost_usd_estimate" if "cost_usd_estimate" in cols else "NULL"
            lat_col = "latency_ms" if "latency_ms" in cols else "NULL"
            proj_col = "project_id" if "project_id" in cols else "NULL"
            by_user = conn.execute(
                f"""
                SELECT user_id,
                       COUNT(*) AS requests,
                       SUM(COALESCE({cost_col}, 0)) AS cost_usd,
                       AVG({lat_col}) AS avg_latency_ms
                FROM generation_usage
                GROUP BY user_id
                ORDER BY cost_usd DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            by_project = conn.execute(
                f"""
                SELECT {proj_col} AS project_id,
                       COUNT(*) AS requests,
                       SUM(COALESCE({cost_col}, 0)) AS cost_usd
                FROM generation_usage
                WHERE {proj_col} IS NOT NULL
                GROUP BY {proj_col}
                ORDER BY cost_usd DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            slowest = conn.execute(
                f"""
                SELECT id, user_id, provider, model, {lat_col} AS latency_ms,
                       status, created_at
                FROM generation_usage
                WHERE {lat_col} IS NOT NULL
                ORDER BY {lat_col} DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            errors = conn.execute(
                """
                SELECT provider, COUNT(*) AS errors
                FROM generation_usage
                WHERE status = 'failed'
                GROUP BY provider
                ORDER BY errors DESC
                """
            ).fetchall()
        return {
            "cost_per_user": [dict(r) for r in by_user],
            "cost_per_project": [dict(r) for r in by_project],
            "slowest_reviews": [dict(r) for r in slowest],
            "error_rate_by_provider": [dict(r) for r in errors],
        }

    def set_mfa_secret(self, user_id: str, secret: str, *, enabled: bool = False) -> None:
        with self._lock, self._connect() as conn:
            now = _iso()
            conn.execute(
                """
                INSERT INTO user_mfa (user_id, totp_secret, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    totp_secret = excluded.totp_secret,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (user_id, secret, 1 if enabled else 0, now, now),
            )
            conn.execute(
                "UPDATE users SET mfa_enabled = ? WHERE id = ?",
                (1 if enabled else 0, user_id),
            )
            conn.commit()

    def get_mfa_secret(self, user_id: str) -> tuple[str, bool] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT totp_secret, enabled FROM user_mfa WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return row["totp_secret"], bool(row["enabled"])

    # ----------------------------------------------------------- ROI / collab
    def record_roi_event(
        self,
        *,
        org_id: str,
        event_type: str,
        project_id: str | None = None,
        user_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        from app.roi.metrics import record_event

        with self._lock, self._connect() as conn:
            eid = record_event(
                conn,
                org_id=org_id,
                event_type=event_type,
                project_id=project_id,
                user_id=user_id,
                payload=payload,
            )
            conn.commit()
            return eid

    def report_agent_runs(
        self,
        *,
        org_id: str,
        project_id: str,
        user_id: str | None,
        runs_before: int,
        runs_after: int,
        notes: str | None = None,
    ) -> str:
        from app.roi.metrics import report_agent_runs

        with self._lock, self._connect() as conn:
            eid = report_agent_runs(
                conn,
                org_id=org_id,
                project_id=project_id,
                user_id=user_id,
                runs_before=runs_before,
                runs_after=runs_after,
                notes=notes,
            )
            conn.commit()
            return eid

    def org_roi_dashboard(self, org_id: str) -> dict[str, Any]:
        from app.roi.metrics import compute_org_roi, snapshot_dict

        with self._lock, self._connect() as conn:
            return snapshot_dict(compute_org_roi(conn, org_id))

    def add_finding_comment(
        self,
        *,
        org_id: str,
        project_id: str,
        finding_id: str,
        user_id: str,
        body: str,
        mention_user_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.collab.store import add_finding_comment

        with self._lock, self._connect() as conn:
            row = add_finding_comment(
                conn,
                org_id=org_id,
                project_id=project_id,
                finding_id=finding_id,
                user_id=user_id,
                body=body,
                mention_user_ids=mention_user_ids,
            )
            conn.commit()
            return row

    def list_finding_comments(
        self, *, project_id: str, finding_id: str
    ) -> list[dict[str, Any]]:
        from app.collab.store import list_finding_comments

        with self._lock, self._connect() as conn:
            return list_finding_comments(
                conn, project_id=project_id, finding_id=finding_id
            )

    def upsert_org_rejected_approach(
        self,
        *,
        org_id: str,
        approach: str,
        reason: str,
        source_project_id: str | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        from app.collab.store import upsert_org_rejected_approach

        with self._lock, self._connect() as conn:
            row = upsert_org_rejected_approach(
                conn,
                org_id=org_id,
                approach=approach,
                reason=reason,
                source_project_id=source_project_id,
                created_by=created_by,
            )
            conn.commit()
            return row

    def list_org_rejected_approaches(self, org_id: str) -> list[dict[str, Any]]:
        from app.collab.store import list_org_rejected_approaches

        with self._lock, self._connect() as conn:
            return list_org_rejected_approaches(conn, org_id=org_id)

    def list_notifications(self, user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        from app.collab.store import list_notifications

        with self._lock, self._connect() as conn:
            return list_notifications(conn, user_id=user_id, limit=limit)

    def list_org_member_ids(self, org_id: str) -> list[str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id FROM org_memberships WHERE org_id = ?",
                (org_id,),
            ).fetchall()
        return [r["user_id"] for r in rows]

    def notify_org_blocking_finding(
        self,
        *,
        org_id: str,
        project_id: str,
        finding_id: str,
        title: str,
    ) -> int:
        from app.collab.store import notify_blocking_finding

        members = self.list_org_member_ids(org_id)
        with self._lock, self._connect() as conn:
            n = notify_blocking_finding(
                conn,
                org_id=org_id,
                project_id=project_id,
                finding_id=finding_id,
                title=title,
                member_user_ids=members,
            )
            conn.commit()
            return n

    def save_org_playbook(
        self,
        *,
        org_id: str,
        title: str,
        content_text: str,
        vertical: str | None,
        created_by: str | None,
        skill_id: str | None,
    ) -> dict[str, Any]:
        from uuid import uuid4

        pid = f"pb_{uuid4().hex[:16]}"
        now = _iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO org_playbooks (
                    id, org_id, title, vertical, content_text, skill_id,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pid,
                    org_id,
                    title.strip(),
                    vertical,
                    content_text,
                    skill_id,
                    created_by,
                    now,
                    now,
                ),
            )
            conn.commit()
        return {
            "id": pid,
            "org_id": org_id,
            "title": title.strip(),
            "vertical": vertical,
            "skill_id": skill_id,
        }
