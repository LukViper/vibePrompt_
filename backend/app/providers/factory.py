"""Build primary failover chain and optional critic from settings."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.providers.base import ModelProvider
from app.providers.failover import FailoverPrimaryProvider
from app.providers.gemini import GeminiProvider
from app.providers.groq import build_groq_provider
from app.providers.openrouter import build_openrouter_provider


@dataclass
class ProviderBundle:
    primary: FailoverPrimaryProvider
    critic: ModelProvider | None
    using_offline_primary: bool = False
    chain_providers: list[ModelProvider] | None = None


def _build_named_provider(name: str, settings: Settings) -> ModelProvider | None:
    timeout = settings.provider_timeout_seconds
    tokens = settings.max_output_tokens
    retries = settings.max_retries

    if name == "gemini":
        return GeminiProvider(
            settings.gemini_api_key,
            settings.gemini_model,
            timeout=timeout,
            max_output_tokens=tokens,
            max_retries=retries,
        )
    if name == "openrouter":
        return build_openrouter_provider(
            settings.openrouter_api_key,
            settings.openrouter_model,
            base_url=settings.openrouter_base_url,
            site_url=settings.openrouter_site_url,
            app_name=settings.openrouter_app_name,
            timeout=timeout,
            max_output_tokens=tokens,
            max_retries=retries,
        )
    if name == "groq":
        return build_groq_provider(
            settings.groq_api_key,
            settings.groq_model,
            base_url=settings.groq_base_url,
            timeout=timeout,
            max_output_tokens=tokens,
            max_retries=retries,
            supports_primary=True,
            supports_critic=True,
        )
    return None


def build_providers(settings: Settings) -> ProviderBundle:
    chain: list[ModelProvider] = []
    for name in settings.provider_order_list:
        provider = _build_named_provider(name, settings)
        if provider is not None:
            chain.append(provider)

    primary = FailoverPrimaryProvider(
        chain,
        per_provider_timeout=settings.provider_timeout_seconds,
        total_budget_seconds=settings.failover_total_budget_seconds,
    )

    critic: ModelProvider | None = None
    if settings.critic_configured:
        critic = build_groq_provider(
            settings.groq_api_key,
            settings.groq_model,
            base_url=settings.groq_base_url,
            timeout=settings.provider_timeout_seconds,
            max_output_tokens=settings.max_output_tokens,
            max_retries=settings.max_retries,
            supports_primary=False,
            supports_critic=True,
        )

    return ProviderBundle(
        primary=primary,
        critic=critic,
        using_offline_primary=not settings.primary_configured,
        chain_providers=chain,
    )
