"""Verify Supabase Auth access tokens via JWKS (preferred) or HS256 JWT secret."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient


class SupabaseAuthError(Exception):
    def __init__(self, message: str, *, code: str = "invalid_token") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class VerifiedSupabaseUser:
    id: str
    email: str | None
    role: str | None
    claims: dict[str, Any]


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


def verify_supabase_access_token(
    token: str,
    *,
    supabase_url: str,
    jwt_issuer: str | None = None,
    jwks_url: str | None = None,
    jwt_secret: str | None = None,
    audience: str = "authenticated",
) -> VerifiedSupabaseUser:
    if not token or not token.strip():
        raise SupabaseAuthError("Missing access token", code="missing_token")

    base = supabase_url.rstrip("/")
    issuer = (jwt_issuer or f"{base}/auth/v1").rstrip("/")
    jwks = jwks_url or f"{base}/auth/v1/.well-known/jwks.json"

    claims: dict[str, Any]
    try:
        if jwt_secret and jwt_secret.strip():
            # Legacy Supabase projects sign with the JWT secret (HS256).
            claims = jwt.decode(
                token,
                jwt_secret.strip(),
                algorithms=["HS256"],
                audience=audience,
                issuer=issuer,
                options={"require": ["exp", "sub"]},
            )
        else:
            client = _jwks_client(jwks)
            signing_key = client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256", "ES384", "ES512"],
                audience=audience,
                issuer=issuer,
                options={"require": ["exp", "sub"]},
            )
    except jwt.ExpiredSignatureError as exc:
        raise SupabaseAuthError("Token expired", code="token_expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise SupabaseAuthError("Invalid token audience", code="invalid_audience") from exc
    except jwt.InvalidIssuerError as exc:
        raise SupabaseAuthError("Invalid token issuer", code="invalid_issuer") from exc
    except jwt.PyJWTError as exc:
        raise SupabaseAuthError("Invalid access token", code="invalid_token") from exc

    sub = claims.get("sub")
    if not sub or not isinstance(sub, str):
        raise SupabaseAuthError("Token missing subject", code="invalid_token")

    email = claims.get("email")
    if isinstance(email, str):
        email = email.strip().lower() or None
    else:
        email = None

    role = claims.get("role")
    if role is not None and not isinstance(role, str):
        role = str(role)

    return VerifiedSupabaseUser(id=sub, email=email, role=role, claims=claims)


def clear_jwks_cache() -> None:
    _jwks_client.cache_clear()
