"""OpenAI-compatible chat completions client (OpenRouter, Groq, etc.)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.providers.base import (
    CandidateFinding,
    CriticReview,
    ModelProvider,
    PrimaryAnalysis,
    ProviderError,
    ProviderErrorKind,
)
from app.providers.parsing import parse_critic_review, parse_primary_analysis
from app.providers.prompts import build_critic_prompt, build_primary_prompt

logger = logging.getLogger("vibeprompt.providers")


def parse_retry_after(headers: httpx.Headers) -> float | None:
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def classify_http_status(status: int, label: str) -> ProviderError:
    if status == 429:
        return ProviderError(ProviderErrorKind.RATE_LIMIT, f"{label} rate limited")
    if status in (401, 403):
        return ProviderError(ProviderErrorKind.AUTH, f"{label} authentication failed")
    if status in (400, 404, 422):
        return ProviderError(
            ProviderErrorKind.INVALID_REQUEST,
            f"{label} invalid request ({status})",
        )
    if status in (500, 502, 503, 504) or status >= 500:
        return ProviderError(
            ProviderErrorKind.UNAVAILABLE,
            f"{label} server error {status}",
        )
    return ProviderError(ProviderErrorKind.OTHER, f"{label} request failed ({status})")


class OpenAICompatProvider(ModelProvider):
    """Primary + critic via OpenAI-compatible /chat/completions."""

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 30.0,
        max_output_tokens: int = 2048,
        max_retries: int = 1,
        extra_headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        supports_primary: bool = True,
        supports_critic: bool = True,
    ) -> None:
        self.name = name
        self.api_key = api_key.strip()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        self.max_retries = max_retries
        self.extra_headers = extra_headers or {}
        self._client = client
        self.supports_primary = supports_primary
        self.supports_critic = supports_critic

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def analyze_primary(
        self,
        *,
        project_snapshot: dict[str, Any],
        user_message: str,
        conversation_tail: list[dict[str, str]],
    ) -> PrimaryAnalysis:
        if not self.supports_primary:
            raise ProviderError(
                ProviderErrorKind.OTHER,
                f"{self.name} is not configured for primary analysis",
            )
        if not self.is_available():
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE,
                f"{self.name} API key not configured",
            )
        prompt = build_primary_prompt(
            project_snapshot=project_snapshot,
            user_message=user_message,
            conversation_tail=conversation_tail,
        )
        text = await self._chat(
            system="You are Grill. Respond with JSON only.",
            user=prompt,
        )
        return parse_primary_analysis(text)

    async def critique(
        self,
        *,
        project_snapshot: dict[str, Any],
        user_message: str,
        candidate_findings: list[CandidateFinding],
        primary_reply: str,
    ) -> CriticReview:
        if not self.supports_critic:
            raise ProviderError(
                ProviderErrorKind.OTHER,
                f"{self.name} is not configured as critic",
            )
        if not self.is_available():
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE,
                f"{self.name} API key not configured",
            )
        prompt = build_critic_prompt(
            project_snapshot=project_snapshot,
            user_message=user_message,
            candidate_findings=[f.model_dump() for f in candidate_findings],
            primary_reply=primary_reply,
        )
        text = await self._chat(
            system="You are an independent critic. Respond with JSON only.",
            user=prompt,
        )
        return parse_critic_review(text)

    async def _chat(self, *, system: str, user: str) -> str:
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": self.max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

        last_error: ProviderError | None = None
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        started = time.perf_counter()
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.post(url, json=body, headers=headers)
                except httpx.TimeoutException as exc:
                    last_error = ProviderError(
                        ProviderErrorKind.TIMEOUT, f"{self.name} timed out"
                    )
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
                        ProviderErrorKind.UNAVAILABLE,
                        f"{self.name} connection error",
                    )
                    if attempt >= self.max_retries:
                        raise last_error from exc
                    continue
                except httpx.HTTPError as exc:
                    last_error = ProviderError(
                        ProviderErrorKind.OTHER, f"{self.name} HTTP error"
                    )
                    if attempt >= self.max_retries:
                        raise last_error from exc
                    continue

                if resp.status_code >= 400:
                    err = classify_http_status(resp.status_code, self.name)
                    err.retry_after = parse_retry_after(resp.headers)
                    last_error = err
                    if err.allows_same_provider_retry and attempt < self.max_retries:
                        continue
                    raise err

                data = resp.json()
                try:
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise ProviderError(
                        ProviderErrorKind.MALFORMED,
                        f"Unexpected {self.name} response shape",
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
                return content if isinstance(content, str) else str(content)
        finally:
            if owns_client:
                await client.aclose()

        raise last_error or ProviderError(ProviderErrorKind.OTHER, f"{self.name} call failed")
