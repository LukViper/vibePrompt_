"""Centralized AI provider routing: BYOK first, then platform Qwen free tier."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.config import Settings
from app.credentials.encryption import CredentialCipher
from app.free_tier.models import FreeTierStatus, FundingSource
from app.persistence.user_store import UserStore
from app.providers.base import ModelProvider
from app.providers.failover import FailoverPrimaryProvider
from app.providers.gemini import GeminiProvider
from app.providers.groq import build_groq_provider
from app.providers.openrouter import build_openrouter_provider
from app.providers.qwen import build_qwen_provider


class InferenceRouteErrorCode(str, Enum):
    BYOK_REQUIRED = "byok_required"
    FREE_TIER_EXHAUSTED = "free_tier_exhausted"
    PLATFORM_PROVIDER_UNAVAILABLE = "platform_provider_unavailable"
    BYOK_INVALID = "byok_invalid"
    RATE_LIMITED = "rate_limited"
    AUTH_REQUIRED = "auth_required"


class InferenceRouteError(Exception):
    def __init__(self, code: InferenceRouteErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ResolvedInference:
    primary: ModelProvider
    critic: ModelProvider | None
    funding_source: FundingSource
    provider: str
    model: str
    using_offline_primary: bool = False


def build_status(
    settings: Settings,
    store: UserStore,
    user_id: str | None,
) -> FreeTierStatus:
    if not settings.free_tier_enabled:
        return FreeTierStatus(
            enabled=False,
            funding="NONE",
            message="Free tier disabled — using legacy platform providers when configured.",
        )

    byok = store.get_active_provider_config(user_id) if user_id else None
    allocation = store.get_free_tier_allocation(user_id) if user_id else None
    allocated = int(allocation["generations_allocated"]) if allocation else 0
    used = int(allocation["generations_used"]) if allocation else 0
    remaining = max(allocated - used, 0)
    exhausted = bool(allocation) and remaining <= 0

    if byok:
        return FreeTierStatus(
            enabled=True,
            allocated=allocated,
            used=used,
            remaining=remaining,
            exhausted=exhausted,
            provider=settings.free_tier_provider,
            model=settings.free_tier_model,
            funding="BYOK",
            byok_configured=True,
            byok_provider=byok["provider"],
            byok_model=byok["model"],
            requires_byok=False,
            inference_provider=byok["provider"],
            message="Using your configured API key (BYOK).",
        )

    if not user_id:
        return FreeTierStatus(
            enabled=True,
            allocated=settings.free_tier_generations,
            used=0,
            remaining=settings.free_tier_generations,
            exhausted=False,
            provider=settings.free_tier_provider,
            model=settings.free_tier_model,
            funding="NONE",
            requires_byok=False,
            message="Sign in to use free generations or configure BYOK.",
        )

    if exhausted:
        return FreeTierStatus(
            enabled=True,
            allocated=allocated,
            used=used,
            remaining=0,
            exhausted=True,
            provider=settings.free_tier_provider,
            model=settings.free_tier_model,
            funding="NONE",
            byok_configured=False,
            requires_byok=True,
            inference_provider=None,
            message="Your free generations are exhausted. Connect your own API key to continue.",
        )

    return FreeTierStatus(
        enabled=True,
        allocated=allocated or settings.free_tier_generations,
        used=used,
        remaining=remaining if allocation else settings.free_tier_generations,
        exhausted=False,
        provider=settings.free_tier_provider,
        model=settings.free_tier_model,
        funding="PLATFORM",
        byok_configured=False,
        requires_byok=False,
        inference_provider=settings.free_tier_provider,
        message="VibePrompt Free Tier",
    )


def resolve_inference(
    *,
    settings: Settings,
    store: UserStore,
    user_id: str,
) -> ResolvedInference:
    """
    Routing priority:
      1. Active BYOK → user's provider/model/key
      2. Free allowance remaining → platform Qwen only
      3. Exhausted → require BYOK (never silent failover to another platform provider)
    """
    byok = store.get_active_provider_config(user_id)
    if byok:
        try:
            cipher = CredentialCipher(settings.credentials_encryption_key)
            api_key = cipher.decrypt(byok["encrypted_api_key"])
        except ValueError as exc:
            raise InferenceRouteError(
                InferenceRouteErrorCode.BYOK_INVALID,
                "Stored API key could not be decrypted. Reconfigure BYOK.",
            ) from exc
        primary = _build_user_provider(
            provider=byok["provider"],
            api_key=api_key,
            model=byok["model"],
            base_url=byok.get("base_url"),
            settings=settings,
        )
        critic = None
        if byok["provider"] in ("groq", "qwen") and settings.critic_enabled:
            critic = _build_user_provider(
                provider=byok["provider"],
                api_key=api_key,
                model=byok["model"],
                base_url=byok.get("base_url"),
                settings=settings,
                for_critic=True,
            )
        return ResolvedInference(
            primary=primary,
            critic=critic,
            funding_source=FundingSource.BYOK,
            provider=byok["provider"],
            model=byok["model"],
        )

    allocation = store.get_free_tier_allocation(user_id)
    if allocation is None:
        store.ensure_free_tier_allocation(
            user_id,
            generations=settings.free_tier_generations,
            provider=settings.free_tier_provider,
            model=settings.free_tier_model,
        )
        allocation = store.get_free_tier_allocation(user_id)
    assert allocation is not None

    remaining = int(allocation["generations_allocated"]) - int(
        allocation["generations_used"]
    )
    if remaining <= 0:
        raise InferenceRouteError(
            InferenceRouteErrorCode.FREE_TIER_EXHAUSTED,
            "Your free generations are exhausted. Configure your own API key (BYOK) to continue.",
        )

    if not settings.qwen_configured or settings.free_tier_provider != "qwen":
        raise InferenceRouteError(
            InferenceRouteErrorCode.PLATFORM_PROVIDER_UNAVAILABLE,
            "Platform Qwen is unavailable. Configure BYOK or contact the administrator.",
        )

    max_out = min(settings.max_output_tokens, settings.free_tier_max_output_tokens)
    primary = build_qwen_provider(
        settings.qwen_api_key,
        settings.free_tier_model,
        base_url=settings.qwen_base_url,
        timeout=settings.provider_timeout_seconds,
        max_output_tokens=max_out,
        max_retries=settings.max_retries,
        supports_primary=True,
        supports_critic=False,
    )
    # No silent failover: wrap as a single-provider "chain".
    wrapped = FailoverPrimaryProvider(
        [primary],
        per_provider_timeout=settings.provider_timeout_seconds,
        total_budget_seconds=settings.failover_total_budget_seconds,
    )
    critic = None
    if settings.critic_enabled:
        critic = build_qwen_provider(
            settings.qwen_api_key,
            settings.free_tier_model,
            base_url=settings.qwen_base_url,
            timeout=settings.provider_timeout_seconds,
            max_output_tokens=max_out,
            max_retries=settings.max_retries,
            supports_primary=False,
            supports_critic=True,
        )

    return ResolvedInference(
        primary=wrapped,
        critic=critic,
        funding_source=FundingSource.PLATFORM,
        provider="qwen",
        model=settings.free_tier_model,
    )


def _build_user_provider(
    *,
    provider: str,
    api_key: str,
    model: str,
    base_url: str | None,
    settings: Settings,
    for_critic: bool = False,
) -> ModelProvider:
    timeout = settings.provider_timeout_seconds
    tokens = settings.max_output_tokens
    retries = settings.max_retries

    if provider == "gemini":
        if for_critic:
            raise InferenceRouteError(
                InferenceRouteErrorCode.BYOK_INVALID,
                "Gemini cannot be used as the independent critic.",
            )
        return GeminiProvider(
            api_key,
            model,
            timeout=timeout,
            max_output_tokens=tokens,
            max_retries=retries,
        )
    if provider == "openrouter":
        if for_critic:
            raise InferenceRouteError(
                InferenceRouteErrorCode.BYOK_INVALID,
                "OpenRouter is not configured as critic in VibePrompt.",
            )
        return build_openrouter_provider(
            api_key,
            model,
            base_url=base_url or settings.openrouter_base_url,
            site_url=settings.openrouter_site_url,
            app_name=settings.openrouter_app_name,
            timeout=timeout,
            max_output_tokens=tokens,
            max_retries=retries,
        )
    if provider == "groq":
        return build_groq_provider(
            api_key,
            model,
            base_url=base_url or settings.groq_base_url,
            timeout=timeout,
            max_output_tokens=tokens,
            max_retries=retries,
            supports_primary=not for_critic,
            supports_critic=True,
        )
    if provider == "qwen":
        return build_qwen_provider(
            api_key,
            model,
            base_url=base_url or settings.qwen_base_url,
            timeout=timeout,
            max_output_tokens=tokens,
            max_retries=retries,
            supports_primary=not for_critic,
            supports_critic=True,
        )
    raise InferenceRouteError(
        InferenceRouteErrorCode.BYOK_INVALID,
        f"Unsupported provider: {provider}",
    )


__all__ = [
    "InferenceRouteError",
    "InferenceRouteErrorCode",
    "ResolvedInference",
    "build_status",
    "resolve_inference",
]
