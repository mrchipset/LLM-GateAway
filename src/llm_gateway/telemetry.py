"""OpenTelemetry wiring for the gateway data plane.

Design rationale lives in ``notes/observability.md``. Two rules matter here:

* tracing is opt-in: with tracing disabled no provider is installed, so spans are
  no-ops and no ``traceparent`` leaves the gateway;
* the inbound ``traceparent`` is untrusted input used only for correlation, never
  for authentication or tenancy.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Span, Status, StatusCode, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from llm_gateway import __version__
from llm_gateway.config import Settings

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger(__name__)

_INSTRUMENTATION_NAME = "llm_gateway"
_PROPAGATOR = TraceContextTextMapPropagator()

_installed_provider: TracerProvider | None = None


@dataclass(frozen=True, slots=True)
class Telemetry:
    """Tracer plus the provider that owns it, so startup and shutdown stay paired."""

    tracer: Tracer
    provider: TracerProvider | None = None

    @property
    def enabled(self) -> bool:
        return self.provider is not None

    def shutdown(self) -> None:
        provider = self.provider
        if provider is None:
            return
        try:
            provider.shutdown()
        except Exception as exc:  # pragma: no cover - defensive shutdown path
            logger.warning(
                "tracing_shutdown_failed",
                extra={"error": type(exc).__name__},
            )


def configure_telemetry(settings: Settings) -> Telemetry:
    """Build the process-wide tracer provider when tracing is enabled."""
    global _installed_provider

    if not settings.tracing_enabled:
        return Telemetry(tracer=trace.get_tracer(_INSTRUMENTATION_NAME))

    if _installed_provider is not None:
        provider = _installed_provider
        return Telemetry(
            tracer=provider.get_tracer(_INSTRUMENTATION_NAME),
            provider=provider,
        )

    provider = _build_provider(settings)
    trace.set_tracer_provider(provider)
    _installed_provider = provider
    return Telemetry(
        tracer=provider.get_tracer(_INSTRUMENTATION_NAME),
        provider=provider,
    )


def _build_provider(settings: Settings) -> TracerProvider:
    # Imported lazily so the SDK and exporter are only paid for when tracing is on.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    exporter = OTLPSpanExporter(
        endpoint=settings.tracing_endpoint,
        timeout=settings.tracing_export_timeout_seconds,
    )
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.tracing_service_name,
                "service.version": __version__,
            }
        ),
        sampler=ParentBased(TraceIdRatioBased(settings.tracing_sample_ratio)),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def extract_trace_context(headers: Mapping[str, str]) -> Context:
    """Parse W3C trace context from lowercase header names.

    Invalid or absent headers yield an empty context, which starts a new trace.
    """
    return _PROPAGATOR.extract(carrier=dict(headers))


def inject_trace_context(headers: MutableMapping[str, str]) -> None:
    """Write the outgoing ``traceparent`` for the currently active span.

    With an invalid or no-op span context this is a no-op, so a disabled gateway
    sends no trace headers upstream.
    """
    _PROPAGATOR.inject(headers)


def current_trace_ids() -> tuple[str | None, str | None]:
    """Return the active ``(trace_id, span_id)`` as lowercase hex, or ``(None, None)``."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None, None
    return format(span_context.trace_id, "032x"), format(span_context.span_id, "016x")


def current_trace_id() -> str | None:
    return current_trace_ids()[0]


def annotate_current_span(attributes: Mapping[str, object]) -> None:
    """Attach attributes to the active span; silently ignored when not recording."""
    span = trace.get_current_span()
    if not span.is_recording():
        return
    for key, value in attributes.items():
        if value is None:
            continue
        span.set_attribute(key, value)  # pyright: ignore[reportArgumentType]


def mark_span_error(span: Span, *, status_code: int | None = None) -> None:
    """Mark a span as failed without leaking the upstream message."""
    if status_code is not None:
        span.set_attribute("http.response.status_code", status_code)
    span.set_status(Status(StatusCode.ERROR))
