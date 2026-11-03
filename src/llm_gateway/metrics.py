"""Process-wide metrics for the gateway data plane.

Metrics are intentionally global: a scrape is a process-level view, and the OTel
instruments are thread-safe. ``current_metrics()`` returns no-op instruments until
:func:`configure_metrics` installs a provider, so importing this module or calling
the helper before startup is safe. Tests replace the installed instruments with
:func:`install_metrics`.

Label policy is deliberately narrow: provider, model, route template, HTTP status,
error code and rejection reason only. Never tenant, key, request id, prompt or any
other per-request value.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, Meter

from llm_gateway import __version__
from llm_gateway.config import Settings

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics import MeterProvider

logger = logging.getLogger(__name__)

_METER_NAME = "llm_gateway"
_DURATION_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)
_TTFT_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

_lock = threading.RLock()
_current: Metrics | None = None
_provider: MeterProvider | None = None
_shutdown: Callable[[], None] | None = None
_started_endpoint: tuple[str, int] | None = None


@dataclass(frozen=True, slots=True)
class Metrics:
    """Every instrument the gateway records into."""

    requests: Counter
    request_duration: Histogram
    upstream_requests: Counter
    upstream_duration: Histogram
    upstream_ttft: Histogram
    rejections: Counter
    usage_write_failures: Counter
    audit_write_failures: Counter


def build_metrics(meter: Meter) -> Metrics:
    return Metrics(
        requests=meter.create_counter(
            "gateway_requests",
            unit="{request}",
            description="HTTP requests handled by the gateway",
        ),
        request_duration=meter.create_histogram(
            "gateway_request_duration_seconds",
            unit="s",
            description="End-to-end gateway request duration",
        ),
        upstream_requests=meter.create_counter(
            "gateway_upstream_requests",
            unit="{request}",
            description="Upstream attempts, including retries",
        ),
        upstream_duration=meter.create_histogram(
            "gateway_upstream_duration_seconds",
            unit="s",
            description="Upstream attempt duration",
        ),
        upstream_ttft=meter.create_histogram(
            "gateway_upstream_ttft_seconds",
            unit="s",
            description="Upstream time to first streamed chunk",
        ),
        rejections=meter.create_counter(
            "gateway_rejections",
            unit="{request}",
            description="Requests rejected by quota or rate limiting",
        ),
        usage_write_failures=meter.create_counter(
            "gateway_usage_write_failures",
            unit="{failure}",
            description="Usage records that failed to persist or were unavailable",
        ),
        audit_write_failures=meter.create_counter(
            "gateway_audit_write_failures",
            unit="{failure}",
            description="Audit turns that failed to persist",
        ),
    )


def current_metrics() -> Metrics:
    global _current
    with _lock:
        if _current is None:
            _current = build_metrics(metrics.get_meter(_METER_NAME))
        return _current


def install_metrics(instruments: Metrics) -> None:
    """Replace the process-wide instruments. Intended for startup and tests."""
    global _current
    with _lock:
        _current = instruments


def _start_metrics_server(host: str, port: int) -> tuple[object, object]:
    from prometheus_client import start_http_server

    return start_http_server(port=port, addr=host)


def configure_metrics(settings: Settings) -> Metrics:
    """Install a Prometheus-backed meter provider when metrics are enabled."""
    global _current, _provider, _shutdown, _started_endpoint

    if not settings.metrics_enabled:
        return current_metrics()

    endpoint = (settings.metrics_host, settings.metrics_port)
    with _lock:
        if _started_endpoint == endpoint:
            return current_metrics()

    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
    from opentelemetry.sdk.resources import Resource

    reader = PrometheusMetricReader()
    provider = MeterProvider(
        metric_readers=[reader],
        resource=Resource.create(
            {
                "service.name": settings.metrics_service_name,
                "service.version": __version__,
            }
        ),
        views=[
            View(
                instrument_name="gateway_request_duration_seconds",
                aggregation=ExplicitBucketHistogramAggregation(_DURATION_BUCKETS),
            ),
            View(
                instrument_name="gateway_upstream_duration_seconds",
                aggregation=ExplicitBucketHistogramAggregation(_DURATION_BUCKETS),
            ),
            View(
                instrument_name="gateway_upstream_ttft_seconds",
                aggregation=ExplicitBucketHistogramAggregation(_TTFT_BUCKETS),
            ),
        ],
    )
    metrics.set_meter_provider(provider)
    instruments = build_metrics(provider.get_meter(_METER_NAME))

    try:
        server, thread = _start_metrics_server(settings.metrics_host, settings.metrics_port)
    except OSError:
        # A metrics endpoint that cannot bind must not take the gateway down.
        logger.error(
            "metrics_endpoint_bind_failed",
            extra={"host": settings.metrics_host, "port": settings.metrics_port},
        )
        with _lock:
            _provider = provider
            _current = instruments
        return instruments

    def shutdown() -> None:
        server.shutdown()  # pyright: ignore[reportAttributeAccessIssue]
        thread.join(timeout=5)  # pyright: ignore[reportAttributeAccessIssue]

    with _lock:
        _provider = provider
        _current = instruments
        _shutdown = shutdown
        _started_endpoint = endpoint
    return instruments


def shutdown_metrics() -> None:
    global _provider, _shutdown, _started_endpoint
    with _lock:
        shutdown = _shutdown
        provider = _provider
        _shutdown = None
        _provider = None
        _started_endpoint = None
    if shutdown is not None:
        try:
            shutdown()
        except Exception as exc:  # pragma: no cover - defensive shutdown path
            logger.warning("metrics_shutdown_failed", extra={"error": type(exc).__name__})
    if provider is not None:
        try:
            provider.shutdown()
        except Exception as exc:  # pragma: no cover - defensive shutdown path
            logger.warning("metrics_shutdown_failed", extra={"error": type(exc).__name__})


def reset_metrics_for_tests() -> None:
    """Drop the installed instruments so a test can install its own."""
    global _current
    with _lock:
        _current = None
