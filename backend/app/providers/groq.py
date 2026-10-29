"""Groq provider — OpenAI-compatible; used as failover primary and/or independent critic."""

from __future__ import annotations

import httpx

from app.providers.openai_compat import OpenAICompatProvider


def build_groq_provider(
    api_key: str,
    model: str,
    *,
    base_url: str = "https://api.groq.com/openai/v1",
    timeout: float = 30.0,
    max_output_tokens: int = 2048,
    max_retries: int = 1,
    client: httpx.AsyncClient | None = None,
    supports_primary: bool = True,
    supports_critic: bool = True,
) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        name="groq",
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout=timeout,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
        client=client,
        supports_primary=supports_primary,
        supports_critic=supports_critic,
    )


# Backward-compatible alias used by older imports/tests
class GroqProvider(OpenAICompatProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float = 30.0,
        max_output_tokens: int = 2048,
        max_retries: int = 1,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.groq.com/openai/v1",
    ) -> None:
        super().__init__(
            name="groq",
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
            max_retries=max_retries,
            client=client,
            supports_primary=True,
            supports_critic=True,
        )
