"""OpenRouter adapter (OpenAI-compatible chat completions)."""

from __future__ import annotations

import httpx

from app.providers.openai_compat import OpenAICompatProvider


def build_openrouter_provider(
    api_key: str,
    model: str,
    *,
    base_url: str = "https://openrouter.ai/api/v1",
    site_url: str = "",
    app_name: str = "VibePrompt",
    timeout: float = 30.0,
    max_output_tokens: int = 2048,
    max_retries: int = 1,
    client: httpx.AsyncClient | None = None,
) -> OpenAICompatProvider:
    extra: dict[str, str] = {}
    if site_url.strip():
        extra["HTTP-Referer"] = site_url.strip()
    if app_name.strip():
        extra["X-Title"] = app_name.strip()

    return OpenAICompatProvider(
        name="openrouter",
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout=timeout,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
        extra_headers=extra,
        client=client,
        supports_primary=True,
        supports_critic=False,
    )
