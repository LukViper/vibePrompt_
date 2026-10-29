"""Ordered provider failover for primary analysis — one provider at a time."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import ModelProvider, PrimaryAnalysis, ProviderError, ProviderErrorKind
from app.providers.mock import heuristic_primary

logger = logging.getLogger("vibeprompt.providers")

PROVIDER_DISPLAY = {
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
    "groq": "Groq",
    "offline": "offline",
    "mock": "offline",
}


@dataclass
class ProviderAttempt:
    provider: str
    model: str | None
    success: bool
    failure_kind: str | None = None
    latency_ms: float | None = None
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class FailoverResult:
    analysis: PrimaryAnalysis
    provider: str
    model: str | None
    offline: bool
    status_message: str
    attempts: list[ProviderAttempt] = field(default_factory=list)
    latency_ms: float | None = None


def display_name(provider: str) -> str:
    return PROVIDER_DISPLAY.get(provider, provider)


def build_status_message(attempts: list[ProviderAttempt], winner: str, *, offline: bool) -> str:
    contacted_failures = [
        a for a in attempts if not a.skipped and not a.success and a.provider != winner
    ]
    configured_any = any(not a.skipped or a.skip_reason != "missing_credentials" for a in attempts)
    all_missing = attempts and all(
        a.skipped and a.skip_reason == "missing_credentials" for a in attempts
    )

    if offline and (all_missing or not any(not a.skipped for a in attempts)):
        if all_missing or not configured_any:
            return "No provider credentials configured"
        return "All external providers unavailable; offline review active"

    if offline:
        failed_names = [display_name(a.provider) for a in contacted_failures]
        if failed_names:
            return (
                f"{' and '.join(failed_names)} unavailable; offline review active"
                if len(failed_names) <= 2
                else "All external providers unavailable; offline review active"
            )
        return "All external providers unavailable; offline review active"

    winner_label = display_name(winner)
    if not contacted_failures:
        return f"{winner_label} responding"

    parts: list[str] = []
    for a in contacted_failures:
        label = display_name(a.provider)
        if a.failure_kind == ProviderErrorKind.RATE_LIMIT.value:
            parts.append(f"{label} rate-limited")
        elif a.failure_kind == ProviderErrorKind.TIMEOUT.value:
            parts.append(f"{label} timed out")
        else:
            parts.append(f"{label} unavailable")

    if len(parts) == 1:
        return f"{parts[0]}; {winner_label} responding"
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}; {winner_label} responding"
    return f"{', '.join(parts[:-1])}, and {parts[-1]}; {winner_label} responding"


def normalize_provider_order(raw: str | list[str], *, default: list[str]) -> list[str]:
    if isinstance(raw, str):
        names = [p.strip().lower() for p in raw.split(",") if p.strip()]
    else:
        names = [str(p).strip().lower() for p in raw if str(p).strip()]

    allowed = {"gemini", "openrouter", "groq"}
    ordered: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name not in allowed:
            logger.warning("Ignoring unknown provider in failover order: %s", name)
            continue
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered or list(default)


class FailoverPrimaryProvider(ModelProvider):
    """Try providers in priority order; fall back to offline heuristics once."""

    name = "failover"

    def __init__(
        self,
        providers: list[ModelProvider],
        *,
        per_provider_timeout: float = 30.0,
        total_budget_seconds: float = 45.0,
        respect_retry_after_within_budget: bool = True,
    ) -> None:
        self.providers = providers
        self.per_provider_timeout = per_provider_timeout
        self.total_budget_seconds = total_budget_seconds
        self.respect_retry_after_within_budget = respect_retry_after_within_budget
        self.last_result: FailoverResult | None = None

    def is_available(self) -> bool:
        # Always available — offline heuristics are the final fallback.
        return True

    async def critique(self, **_: Any) -> Any:
        raise ProviderError(
            ProviderErrorKind.OTHER,
            "Failover chain is for primary analysis only",
        )

    async def analyze_primary(
        self,
        *,
        project_snapshot: dict[str, Any],
        user_message: str,
        conversation_tail: list[dict[str, str]],
    ) -> PrimaryAnalysis:
        result = await self.run_primary(
            project_snapshot=project_snapshot,
            user_message=user_message,
            conversation_tail=conversation_tail,
        )
        return result.analysis

    async def run_primary(
        self,
        *,
        project_snapshot: dict[str, Any],
        user_message: str,
        conversation_tail: list[dict[str, str]],
    ) -> FailoverResult:
        attempts: list[ProviderAttempt] = []
        deadline = time.monotonic() + self.total_budget_seconds
        chain_started = time.perf_counter()

        for provider in self.providers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.info(
                    "failover_budget_exhausted",
                    extra={"provider": provider.name, "decision": "stop"},
                )
                break

            model = getattr(provider, "model", None)
            if not provider.is_available():
                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        model=model,
                        success=False,
                        skipped=True,
                        skip_reason="missing_credentials",
                    )
                )
                logger.info(
                    "provider_skipped",
                    extra={
                        "provider": provider.name,
                        "success": False,
                        "failure_kind": "missing_credentials",
                        "failover": True,
                    },
                )
                continue

            attempt_timeout = min(self.per_provider_timeout, remaining)
            started = time.perf_counter()
            try:
                analysis = await asyncio.wait_for(
                    provider.analyze_primary(
                        project_snapshot=project_snapshot,
                        user_message=user_message,
                        conversation_tail=conversation_tail,
                    ),
                    timeout=attempt_timeout,
                )
            except asyncio.TimeoutError:
                latency = round((time.perf_counter() - started) * 1000, 1)
                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        model=model,
                        success=False,
                        failure_kind=ProviderErrorKind.TIMEOUT.value,
                        latency_ms=latency,
                    )
                )
                logger.info(
                    "provider_attempt",
                    extra={
                        "provider": provider.name,
                        "success": False,
                        "failure_kind": "timeout",
                        "latency_ms": latency,
                        "failover_decision": "next",
                    },
                )
                continue
            except ProviderError as exc:
                latency = round((time.perf_counter() - started) * 1000, 1)
                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        model=model,
                        success=False,
                        failure_kind=exc.kind.value,
                        latency_ms=latency,
                    )
                )
                logger.info(
                    "provider_attempt",
                    extra={
                        "provider": provider.name,
                        "success": False,
                        "failure_kind": exc.kind.value,
                        "latency_ms": latency,
                        "failover_decision": "next" if exc.is_failover_worthy else "next",
                    },
                )
                # Auth / invalid request: do not retry same provider; move on.
                if (
                    exc.kind == ProviderErrorKind.RATE_LIMIT
                    and exc.retry_after is not None
                    and self.respect_retry_after_within_budget
                ):
                    wait = exc.retry_after
                    if wait > 0 and (time.monotonic() + wait) < deadline:
                        await asyncio.sleep(wait)
                        # One bounded retry on same provider after Retry-After
                        try:
                            analysis = await asyncio.wait_for(
                                provider.analyze_primary(
                                    project_snapshot=project_snapshot,
                                    user_message=user_message,
                                    conversation_tail=conversation_tail,
                                ),
                                timeout=min(self.per_provider_timeout, deadline - time.monotonic()),
                            )
                            return self._success(
                                analysis,
                                provider.name,
                                model,
                                attempts,
                                chain_started,
                            )
                        except (ProviderError, asyncio.TimeoutError):
                            pass
                continue
            except Exception:
                latency = round((time.perf_counter() - started) * 1000, 1)
                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        model=model,
                        success=False,
                        failure_kind=ProviderErrorKind.OTHER.value,
                        latency_ms=latency,
                    )
                )
                logger.info(
                    "provider_attempt",
                    extra={
                        "provider": provider.name,
                        "success": False,
                        "failure_kind": "other",
                        "latency_ms": latency,
                        "failover_decision": "next",
                    },
                )
                continue

            return self._success(analysis, provider.name, model, attempts, chain_started)

        # Offline heuristic — never partial-merge with failed provider output
        analysis = heuristic_primary(
            project_snapshot=project_snapshot,
            user_message=user_message,
            conversation_tail=conversation_tail,
        )
        status = build_status_message(attempts, "offline", offline=True)
        result = FailoverResult(
            analysis=analysis,
            provider="offline",
            model=None,
            offline=True,
            status_message=status,
            attempts=attempts,
            latency_ms=round((time.perf_counter() - chain_started) * 1000, 1),
        )
        logger.info(
            "failover_complete",
            extra={
                "provider": "offline",
                "success": True,
                "failure_kind": None,
                "offline": True,
                "status_message": status,
            },
        )
        self.last_result = result
        return result

    def _success(
        self,
        analysis: PrimaryAnalysis,
        provider_name: str,
        model: str | None,
        attempts: list[ProviderAttempt],
        chain_started: float,
    ) -> FailoverResult:
        attempts.append(
            ProviderAttempt(
                provider=provider_name,
                model=model,
                success=True,
                latency_ms=None,
            )
        )
        status = build_status_message(attempts, provider_name, offline=False)
        result = FailoverResult(
            analysis=analysis,
            provider=provider_name,
            model=model,
            offline=False,
            status_message=status,
            attempts=attempts,
            latency_ms=round((time.perf_counter() - chain_started) * 1000, 1),
        )
        logger.info(
            "failover_complete",
            extra={
                "provider": provider_name,
                "model": model,
                "success": True,
                "status_message": status,
                "offline": False,
            },
        )
        self.last_result = result
        return result
