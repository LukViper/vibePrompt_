"""Auth API models. Never include password hashes or API keys."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserRecord(BaseModel):
    """Internal user row. password_hash is only for legacy local auth."""

    id: str
    email: str
    password_hash: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    auth_provider: str = "legacy"
    created_at: datetime


class UserPublic(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    avatar_url: str | None = None
    auth_provider: str = "legacy"
    created_at: datetime


class RegisterRequest(BaseModel):
    """Legacy local registration only — unused when Supabase Auth is enabled."""

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("Invalid email address")
        return email


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class ProfileSyncRequest(BaseModel):
    """Optional profile hints from the client after Supabase Auth — never trusted for user id."""

    display_name: str | None = Field(default=None, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=2048)
    auth_provider: str | None = Field(default=None, max_length=40)


class GoogleAuthRequest(BaseModel):
    """Google Identity Services credential (ID token) from the browser button."""

    id_token: str = Field(min_length=20, max_length=8192)


class AuthConfigPublic(BaseModel):
    mode: str  # supabase | legacy
    supabase_configured: bool
    google_oauth_hint: bool = False
    github_oauth_hint: bool = False
    google_client_id: str | None = None
    email_auth: bool = True
    guest_sessions_enabled: bool = True


class GuestAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "guest"
    expires_in_minutes: int
    generations_allocated: int
    user: UserPublic
