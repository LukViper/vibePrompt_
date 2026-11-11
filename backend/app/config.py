"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.providers.failover import normalize_provider_order
from app.providers.qwen import DEFAULT_QWEN_BASE_URL, DEFAULT_QWEN_MODEL

ReviewIntensity = Literal["low", "normal", "high"]
AppEnvironment = Literal["development", "production"]

DEFAULT_PRIMARY_PROVIDER_ORDER = ["gemini", "openrouter", "groq"]

# Packaged defaults that must never be used when APP_ENV=production
INSECURE_JWT_SECRETS = frozenset(
    {
        "dev-only-change-me-vibeprompt-jwt",
        "change-me",
        "secret",
        "jwt-secret",
    }
)
INSECURE_CREDENTIALS_KEYS = frozenset(
    {
        "dev-only-change-me-vibeprompt-creds",
        "change-me",
        "secret",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    # OpenRouter (first failover)
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = ""
    openrouter_app_name: str = "VibePrompt"

    # Groq (second failover + optional independent critic)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Platform-funded Qwen free tier (shared credentials — never per-user keys)
    free_tier_enabled: bool = False
    free_tier_provider: str = "qwen"
    free_tier_model: str = DEFAULT_QWEN_MODEL
    free_tier_generations: int = 20
    free_tier_max_input_tokens: int = 8_000
    free_tier_max_output_tokens: int = 2_048
    free_tier_rate_limit_per_minute: int = 10
    qwen_api_key: str = ""
    qwen_base_url: str = DEFAULT_QWEN_BASE_URL

    # Auth / BYOK
    jwt_secret: str = "dev-only-change-me-vibeprompt-jwt"
    jwt_expires_minutes: int = 60 * 24 * 7
    credentials_encryption_key: str = "dev-only-change-me-vibeprompt-creds"
    auth_required_when_free_tier: bool = True
    # auto | supabase | legacy — auto uses Supabase when SUPABASE_URL is set
    auth_mode: str = "auto"
    supabase_url: str = ""
    supabase_anon_key: str = ""  # never the service-role key
    supabase_jwt_issuer: str = ""
    supabase_jwks_url: str = ""
    # Optional HS256 secret from Supabase project settings (legacy signing)
    supabase_jwt_secret: str = ""
    # Frontend hints only — actual OAuth enablement is in the Supabase dashboard
    supabase_google_oauth_enabled: bool = False
    supabase_github_oauth_enabled: bool = False

    # Failover / orchestration
    primary_provider_order: str = "gemini,openrouter,groq"
    critic_enabled: bool = True
    review_intensity: ReviewIntensity = "normal"
    provider_timeout_seconds: float = 30.0
    failover_total_budget_seconds: float = 45.0
    max_output_tokens: int = 2048
    max_retries: int = 1
    max_request_chars: int = 32_000
    # Mode-aware generation defaults (adapters map to supported API fields)
    temperature_conversational: float = 0.6
    temperature_brainstorming: float = 0.8
    temperature_grill_review: float = 0.3
    temperature_explore: float = 0.6
    temperature_plan: float = 0.7
    temperature_build: float = 0.35
    temperature_review: float = 0.3
    temperature_debug: float = 0.3
    history_max_messages: int = 12
    history_max_chars: int = 2000
    # Conversation memory / summarization
    summary_min_messages: int = 16
    summary_min_new_messages: int = 8
    summary_keep_recent: int = 8
    context_max_total_chars: int = 28_000
    context_max_summary_chars: int = 4_000

    # Persistence
    database_path: str = "./data/vibeprompt.db"
    knowledge_upload_dir: str = "./data/knowledge/uploads"
    skills_dir: str = "./data/skills"
    knowledge_max_upload_bytes: int = 40 * 1024 * 1024
    # Comma-separated admin emails for Knowledge Library. If empty and free tier
    # is off, any authenticated user may administer (local single-tenant). If free
    # tier is on, ADMIN_EMAILS must be set.
    admin_emails: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_secret: str = ""
    # development | production — also accepts ENV / APP_ENV via env vars
    app_env: str = "development"

    @field_validator("review_intensity", mode="before")
    @classmethod
    def normalize_intensity(cls, value: object) -> object:
        if isinstance(value, str):
            return value.lower().strip()
        return value

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_app_env(cls, value: object) -> object:
        if isinstance(value, str):
            raw = value.lower().strip()
            if raw in {"prod", "production"}:
                return "production"
            if raw in {"dev", "development", "local", "test", ""}:
                return "development"
            return raw
        return value

    @field_validator("free_tier_provider", mode="before")
    @classmethod
    def normalize_free_tier_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.lower().strip() or "qwen"
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]

    def is_admin_email(self, email: str | None) -> bool:
        if not email:
            return False
        allow = self.admin_email_list
        if not allow:
            # Local/dev: open Knowledge Library admin when free tier is disabled
            return not self.free_tier_enabled
        return email.strip().lower() in allow

    def is_configured_admin(self, email: str | None) -> bool:
        """True only when ADMIN_EMAILS is explicitly set and email is listed.

        Used for cross-project access — never treat 'open local admin' as
        multi-tenant superuser.
        """
        if not email or not self.admin_email_list:
            return False
        return email.strip().lower() in self.admin_email_list

    @property
    def is_production(self) -> bool:
        return (self.app_env or "development").strip().lower() == "production"

    @property
    def requires_authentication(self) -> bool:
        """Production always requires auth; free-tier mode can require it in any env."""
        if self.is_production:
            return True
        return bool(self.free_tier_enabled and self.auth_required_when_free_tier)

    def uses_insecure_jwt_secret(self) -> bool:
        secret = (self.jwt_secret or "").strip()
        if not secret:
            return True
        if secret in INSECURE_JWT_SECRETS:
            return True
        if secret.startswith("dev-only"):
            return True
        return len(secret) < 16

    def uses_insecure_credentials_key(self) -> bool:
        secret = (self.credentials_encryption_key or "").strip()
        if not secret:
            return True
        if secret in INSECURE_CREDENTIALS_KEYS:
            return True
        if secret.startswith("dev-only"):
            return True
        return len(secret) < 16

    def validate_production_settings(self) -> list[str]:
        """Return human-readable errors if production config is unsafe. Empty = ok."""
        if not self.is_production:
            return []
        errors: list[str] = []
        if not (self.api_secret or "").strip():
            errors.append(
                "API_SECRET is required in production and must be a non-empty shared secret"
            )
        if self.uses_insecure_jwt_secret():
            errors.append(
                "JWT_SECRET must be explicitly set to a strong non-development value in production"
            )
        if self.uses_insecure_credentials_key():
            errors.append(
                "CREDENTIALS_ENCRYPTION_KEY must be explicitly set to a strong "
                "non-development value in production"
            )
        return errors

    def assert_secure_for_runtime(self) -> None:
        """Raise RuntimeError when production secrets are missing or insecure."""
        errors = self.validate_production_settings()
        if errors:
            raise RuntimeError(
                "Refusing to start in production with insecure configuration:\n- "
                + "\n- ".join(errors)
            )

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url.strip())

    @property
    def effective_auth_mode(self) -> str:
        mode = (self.auth_mode or "auto").strip().lower()
        if mode == "legacy":
            return "legacy"
        if mode == "supabase":
            return "supabase"
        return "supabase" if self.supabase_url.strip() else "legacy"

    @property
    def supabase_issuer(self) -> str:
        if self.supabase_jwt_issuer.strip():
            return self.supabase_jwt_issuer.strip().rstrip("/")
        if self.supabase_url.strip():
            return f"{self.supabase_url.strip().rstrip('/')}/auth/v1"
        return ""

    @property
    def supabase_jwks(self) -> str:
        if self.supabase_jwks_url.strip():
            return self.supabase_jwks_url.strip()
        if self.supabase_url.strip():
            return (
                f"{self.supabase_url.strip().rstrip('/')}"
                "/auth/v1/.well-known/jwks.json"
            )
        return ""

    @property
    def provider_order_list(self) -> list[str]:
        return normalize_provider_order(
            self.primary_provider_order,
            default=DEFAULT_PRIMARY_PROVIDER_ORDER,
        )

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key.strip())

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key.strip())

    @property
    def qwen_configured(self) -> bool:
        return bool(self.qwen_api_key.strip())

    @property
    def primary_configured(self) -> bool:
        """True if any external primary-chain provider has credentials."""
        return any(
            {
                "gemini": self.gemini_configured,
                "openrouter": self.openrouter_configured,
                "groq": self.groq_configured,
            }.get(name, False)
            for name in self.provider_order_list
        )

    @property
    def critic_configured(self) -> bool:
        return self.groq_configured and self.critic_enabled

    @property
    def free_tier_ready(self) -> bool:
        return (
            self.free_tier_enabled
            and self.free_tier_provider == "qwen"
            and self.qwen_configured
            and self.free_tier_generations > 0
        )

    def provider_status(self) -> dict[str, object]:
        # Never expose API keys.
        return {
            "primary_available": self.primary_configured or self.free_tier_ready,
            "critic_available": self.critic_configured,
            "critic_enabled": self.critic_enabled,
            "review_intensity": self.review_intensity,
            "provider_order": self.provider_order_list,
            "gemini_configured": self.gemini_configured,
            "openrouter_configured": self.openrouter_configured,
            "groq_configured": self.groq_configured,
            "qwen_configured": self.qwen_configured,
            "free_tier_enabled": self.free_tier_enabled,
            "free_tier_ready": self.free_tier_ready,
            "free_tier_provider": self.free_tier_provider if self.free_tier_enabled else None,
            "free_tier_model": self.free_tier_model if self.free_tier_enabled else None,
            "free_tier_generations": (
                self.free_tier_generations if self.free_tier_enabled else None
            ),
            "primary_model": self.gemini_model if self.gemini_configured else None,
            "openrouter_model": self.openrouter_model if self.openrouter_configured else None,
            "critic_model": self.groq_model if self.critic_configured else None,
            "gemini_model": self.gemini_model if self.gemini_configured else None,
            "groq_model": self.groq_model if self.groq_configured else None,
        }

    def admin_free_tier_config(self) -> dict[str, object]:
        """Admin-safe free-tier config (no platform API key)."""
        return {
            "enabled": self.free_tier_enabled,
            "provider": self.free_tier_provider,
            "model": self.free_tier_model,
            "generations": self.free_tier_generations,
            "max_input_tokens": self.free_tier_max_input_tokens,
            "max_output_tokens": self.free_tier_max_output_tokens,
            "rate_limit_per_minute": self.free_tier_rate_limit_per_minute,
            "qwen_configured": self.qwen_configured,
            "platform_key_configured": self.qwen_configured,
        }


@lru_cache
def get_settings() -> Settings:
    import os

    # Allow ENV as an alias for APP_ENV when APP_ENV is unset
    if not os.environ.get("APP_ENV") and os.environ.get("ENV"):
        os.environ["APP_ENV"] = os.environ["ENV"]
    return Settings()
