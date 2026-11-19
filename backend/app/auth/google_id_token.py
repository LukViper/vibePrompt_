"""Verify Google Sign-In ID tokens without the google-auth package."""

from __future__ import annotations

from typing import Any

import httpx


class GoogleIdTokenError(ValueError):
    """Raised when a Google ID token is missing, expired, or audience-mismatched."""


def verify_google_id_token(id_token: str, *, client_id: str) -> dict[str, Any]:
    """
    Validate a Google Identity Services ID token via Google's tokeninfo endpoint.

    Checks audience, issuer, and email_verified. Returns the token claims on success.
    """
    token = (id_token or "").strip()
    expected_aud = (client_id or "").strip()
    if not token:
        raise GoogleIdTokenError("Missing Google ID token")
    if not expected_aud:
        raise GoogleIdTokenError("Google OAuth client ID is not configured on the server")

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"id_token": token},
            )
    except httpx.HTTPError as exc:
        raise GoogleIdTokenError("Unable to reach Google token verification") from exc

    if res.status_code != 200:
        raise GoogleIdTokenError("Invalid or expired Google ID token")

    claims = res.json()
    aud = str(claims.get("aud") or "")
    if aud != expected_aud:
        raise GoogleIdTokenError("Google ID token audience mismatch")

    iss = str(claims.get("iss") or "")
    if iss not in ("accounts.google.com", "https://accounts.google.com"):
        raise GoogleIdTokenError("Google ID token issuer is not trusted")

    if str(claims.get("email_verified") or "").lower() not in ("true", "1"):
        raise GoogleIdTokenError("Google account email is not verified")

    email = str(claims.get("email") or "").strip().lower()
    sub = str(claims.get("sub") or "").strip()
    if not email or not sub:
        raise GoogleIdTokenError("Google ID token missing email or subject")

    return claims
