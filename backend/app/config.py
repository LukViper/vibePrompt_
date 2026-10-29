"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.providers.failover import normalize_provider_order

ReviewIntensity = Literal["low", "normal", "high"]

DEFAULT_PRIMARY_PROVIDER_ORDER = ["gemini", "openrouter", "groq"]


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

    # Failover / orchestration
    primary_provider_order: str = "gemini,openrouter,groq"
    critic_enabled: bool = True
    review_intensity: ReviewIntensity = "normal"
    provider_timeout_seconds: float = 30.0
    failover_total_budget_seconds: float = 45.0
    max_output_tokens: int = 2048
    max_retries: int = 1
    max_request_chars: int = 32_000

    # Persistence
    database_path: str = "./data/vibeprompt.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_secret: str = ""

    @field_validator("review_intensity", mode="before")
    @classmethod
    def normalize_intensity(cls, value: object) -> object:
        if isinstance(value, str):
            return value.lower().strip()
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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

    def provider_status(self) -> dict[str, object]:
        return {
            "primary_available": self.primary_configured,
            "critic_available": self.critic_configured,
            "critic_enabled": self.critic_enabled,
            "review_intensity": self.review_intensity,
            "provider_order": self.provider_order_list,
            "gemini_configured": self.gemini_configured,
            "openrouter_configured": self.openrouter_configured,
            "groq_configured": self.groq_configured,
            "primary_model": self.gemini_model if self.gemini_configured else None,
            "openrouter_model": self.openrouter_model if self.openrouter_configured else None,
            "critic_model": self.groq_model if self.critic_configured else None,
            "gemini_model": self.gemini_model if self.gemini_configured else None,
            "groq_model": self.groq_model if self.groq_configured else None,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
