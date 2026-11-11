"""Alibaba Cloud Qwen (DashScope) via OpenAI-compatible chat completions."""

from __future__ import annotations

import httpx

from app.providers.openai_compat import OpenAICompatProvider

# MuleRouter OpenAI-compatible gateway (sk-mr-… keys).
# Use /vendors/openai/v1 — the short /v1 alias may 404 for some accounts.
DEFAULT_QWEN_BASE_URL = "https://api.mulerouter.ai/vendors/openai/v1"
DEFAULT_QWEN_MODEL = "qwen3.5-flash"


def build_qwen_provider(
    api_key: str,
    model: str,
    *,
    base_url: str = DEFAULT_QWEN_BASE_URL,
    timeout: float = 30.0,
    max_output_tokens: int = 2048,
    max_retries: int = 1,
    client: httpx.AsyncClient | None = None,
    supports_primary: bool = True,
    supports_critic: bool = True,
) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        name="qwen",
        api_key=api_key,
        model=model or DEFAULT_QWEN_MODEL,
        base_url=(base_url or DEFAULT_QWEN_BASE_URL).rstrip("/"),
        timeout=timeout,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
        client=client,
        supports_primary=supports_primary,
        supports_critic=supports_critic,
    )
