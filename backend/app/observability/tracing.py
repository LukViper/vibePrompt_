"""OpenTelemetry helpers + per-request cost logging for GrillEngine."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import Settings

logger = logging.getLogger("vibeprompt.cost")

_tracer = None


def init_tracing(settings: Settings) -> None:
    """Best-effort OTEL setup; no-op when exporter unset or package missing."""
    global _tracer
    endpoint = (settings.otel_exporter_otlp_endpoint or "").strip()
    if not endpoint:
        _tracer = None
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": settings.otel_service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(settings.otel_service_name)
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.warning("OpenTelemetry init failed: %s", exc)
        _tracer = None


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as sp:
        for k, v in attrs.items():
            if v is not None:
                sp.set_attribute(k, v)
        yield sp


def new_trace_id() -> str:
    return uuid.uuid4().hex


def estimate_cost_usd(
    settings: Settings,
    *,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float:
    inn = max(0, int(input_tokens or 0))
    out = max(0, int(output_tokens or 0))
    return (inn / 1000.0) * settings.cost_usd_per_1k_input_tokens + (
        out / 1000.0
    ) * settings.cost_usd_per_1k_output_tokens


def log_generation_cost(
    *,
    trace_id: str,
    provider: str | None,
    model: str | None,
    latency_ms: float,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_usd: float,
    success: bool,
    project_id: str | None = None,
    user_id: str | None = None,
) -> None:
    logger.info(
        "generation_cost trace_id=%s provider=%s model=%s latency_ms=%.1f "
        "input_tokens=%s output_tokens=%s cost_usd=%.6f success=%s "
        "project_id=%s user_id=%s",
        trace_id,
        provider,
        model,
        latency_ms,
        input_tokens,
        output_tokens,
        cost_usd,
        success,
        project_id,
        user_id,
    )


class Timer:
    def __init__(self) -> None:
        self.start = time.perf_counter()

    def ms(self) -> float:
        return (time.perf_counter() - self.start) * 1000.0
