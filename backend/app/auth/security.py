"""Password hashing and JWT helpers. Never log secrets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def create_access_token(
    *,
    user_id: str,
    email: str,
    secret: str,
    expires_minutes: int = 60 * 24 * 7,
    role: str = "user",
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def create_guest_token(
    *,
    guest_id: str,
    secret: str,
    expires_minutes: int = 180,
) -> str:
    """Short-lived guest JWT — replaces static client-bundled API secrets."""
    return create_access_token(
        user_id=guest_id,
        email=f"{guest_id}@guest.local",
        secret=secret,
        expires_minutes=expires_minutes,
        role="guest",
    )


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"require": ["exp", "sub"]},
    )
