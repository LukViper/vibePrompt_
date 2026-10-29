"""Google Gemini primary provider via the Generative Language REST API."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.providers.base import (
    ModelProvider,
    PrimaryAnalysis,
    ProviderError,
    ProviderErrorKind,
)
from app.providers.openai_compat import classify_http_status, parse_retry_after
from app.providers.parsing import parse_primary_analysis
from app.providers.prompts import build_primary_prompt

logger = logging.getLogger("vibeprompt.providers")


class GeminiProvider(ModelProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float = 30.0,
        max_output_tokens: int = 2048,
        max_retries: int = 1,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        self.max_retries = max_retries
        self._client = client

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def analyze_primary(
        self,
        *,
        project_snapshot: dict[str, Any],
        user_message: str,
        conversation_tail: list[dict[str, str]],
    ) -> PrimaryAnalysis:
        if not self.is_available():
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "Gemini API key not configured")

        prompt = build_primary_prompt(
            project_snapshot=project_snapshot,
            user_message=user_message,
            conversation_tail=conversation_tail,
        )
        text = await self._generate(prompt)
        return parse_primary_analysis(text)

    async def critique(self, **_: Any) -> Any:
        raise ProviderError(
            ProviderErrorKind.OTHER,
            "Gemini is not used as the independent critic in this deployment",
        )

    async def _generate(self, prompt: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}

        last_error: ProviderError | None = None
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        started = time.perf_counter()
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.post(url, json=body, headers=headers)
                except httpx.TimeoutException as exc:
                    last_error = ProviderError(ProviderErrorKind.TIMEOUT, "Gemini timed out")
                    logger.info(
                        "provider_attempt",
                        extra={
                            "provider": self.name,
                            "success": False,
                            "failure_kind": "timeout",
                            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                        },
                    )
                    if attempt >= self.max_retries:
                        raise last_error from exc
                    continue
                except httpx.TransportError as exc:
                    last_error = ProviderError(
                        ProviderErrorKind.UNAVAILABLE, "Gemini connection error"
                    )
                    if attempt >= self.max_retries:
                        raise last_error from exc
                    continue
                except httpx.HTTPError as exc:
                    last_error = ProviderError(ProviderErrorKind.OTHER, "Gemini HTTP error")
                    if attempt >= self.max_retries:
                        raise last_error from exc
                    continue

                if resp.status_code >= 400:
                    err = classify_http_status(resp.status_code, "Gemini")
                    err.retry_after = parse_retry_after(resp.headers)
                    last_error = err
                    if err.allows_same_provider_retry and attempt < self.max_retries:
                        continue
                    raise err

                data = resp.json()
                try:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise ProviderError(
                        ProviderErrorKind.MALFORMED, "Unexpected Gemini response shape"
                    ) from exc

                logger.info(
                    "provider_attempt",
                    extra={
                        "provider": self.name,
                        "model": self.model,
                        "success": True,
                        "failure_kind": None,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
                return text
        finally:
            if owns_client:
                await client.aclose()

        raise last_error or ProviderError(ProviderErrorKind.OTHER, "Gemini call failed")
