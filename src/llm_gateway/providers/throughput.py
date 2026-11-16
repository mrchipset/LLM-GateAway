"""Derive effective upstream throughput from stream timing.

The gateway cannot see the inference engine's internal timings, so these rates are
measured at the adapter boundary:

- **prefill**: non-cached prompt tokens divided by time to the first streamed chunk.
  This includes connection setup, upstream queueing, and network latency, so it is
  an effective lower bound on engine prefill speed.
- **decode**: completion tokens after the first, divided by the interval between
  the first and last streamed chunk. Backpressure from a slow client lengthens that
  interval, so the value is a lower bound as well.

Only streaming requests expose a first-chunk timestamp. Non-streaming requests have
no split between prefill and decode, so they record neither metric.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import time

from opentelemetry.trace import Span

from llm_gateway.metrics import current_metrics
from llm_gateway.schemas.chat import Usage

THROUGHPUT_WINDOW_SECONDS = 900
_MAX_SAMPLES_PER_MODEL = 120

_samples: dict[tuple[str, str], deque[tuple[float, float | None, float | None]]] = {}
_samples_lock = Lock()


@dataclass(frozen=True, slots=True)
class Throughput:
    prefill_tokens_per_second: float | None
    decode_tokens_per_second: float | None


@dataclass(frozen=True, slots=True)
class ThroughputStats:
    """Recent throughput for one provider/model pair, exposed to the console."""

    provider: str
    model: str
    samples: int
    prefill_tokens_per_second_p50: float | None
    prefill_tokens_per_second_p95: float | None
    decode_tokens_per_second_p50: float | None
    decode_tokens_per_second_p95: float | None
    last_observed_at: datetime | None


def compute_throughput(
    *,
    usage: Usage | None,
    ttft_seconds: float,
    decode_seconds: float,
) -> Throughput:
    if usage is None:
        return Throughput(prefill_tokens_per_second=None, decode_tokens_per_second=None)

    prompt_tokens = _non_cached_prompt_tokens(usage)
    prefill = prompt_tokens / ttft_seconds if prompt_tokens > 0 and ttft_seconds > 0 else None

    decode_tokens = usage.completion_tokens - 1
    decode = decode_tokens / decode_seconds if decode_tokens > 0 and decode_seconds > 0 else None

    return Throughput(prefill_tokens_per_second=prefill, decode_tokens_per_second=decode)


def record_stream_throughput(
    *,
    provider: str,
    model: str,
    span: Span | None,
    usage: Usage | None,
    ttft_seconds: float,
    decode_seconds: float,
) -> None:
    result = compute_throughput(
        usage=usage,
        ttft_seconds=ttft_seconds,
        decode_seconds=decode_seconds,
    )
    attributes = {"provider": provider, "model": model}
    metrics = current_metrics()

    prefill = result.prefill_tokens_per_second
    if prefill is not None:
        metrics.upstream_prefill_tokens_per_second.record(prefill, attributes)
        if span is not None:
            span.set_attribute("llm.prefill_tokens_per_second", round(prefill, 2))

    decode = result.decode_tokens_per_second
    if decode is not None:
        metrics.upstream_decode_tokens_per_second.record(decode, attributes)
        if span is not None:
            span.set_attribute("llm.decode_tokens_per_second", round(decode, 2))

    if prefill is not None or decode is not None:
        _remember(provider=provider, model=model, prefill=prefill, decode=decode)


def recent_throughput(*, now: float | None = None) -> list[ThroughputStats]:
    """Aggregate the rolling window, newest data only, sorted by provider and model."""
    current = time() if now is None else now
    cutoff = current - THROUGHPUT_WINDOW_SECONDS
    result: list[ThroughputStats] = []

    with _samples_lock:
        empty: list[tuple[str, str]] = []
        for key, bucket in _samples.items():
            kept = [sample for sample in bucket if sample[0] >= cutoff]
            if not kept:
                empty.append(key)
                continue
            bucket.clear()
            bucket.extend(kept)
            prefill = [sample[1] for sample in kept if sample[1] is not None]
            decode = [sample[2] for sample in kept if sample[2] is not None]
            provider, model = key
            result.append(
                ThroughputStats(
                    provider=provider,
                    model=model,
                    samples=len(kept),
                    prefill_tokens_per_second_p50=_percentile(prefill, 0.50),
                    prefill_tokens_per_second_p95=_percentile(prefill, 0.95),
                    decode_tokens_per_second_p50=_percentile(decode, 0.50),
                    decode_tokens_per_second_p95=_percentile(decode, 0.95),
                    last_observed_at=datetime.fromtimestamp(kept[-1][0], UTC),
                )
            )
        for key in empty:
            del _samples[key]

    return sorted(result, key=lambda item: (item.provider, item.model))


def reset_throughput_window() -> None:
    """Drop the rolling window. Intended for tests."""
    with _samples_lock:
        _samples.clear()


def _remember(
    *,
    provider: str,
    model: str,
    prefill: float | None,
    decode: float | None,
) -> None:
    observed_at = time()
    with _samples_lock:
        bucket = _samples.setdefault((provider, model), deque(maxlen=_MAX_SAMPLES_PER_MODEL))
        bucket.append((observed_at, prefill, decode))


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _non_cached_prompt_tokens(usage: Usage) -> int:
    """Prompt tokens the engine had to prefill, when the provider reports cache hits."""
    details = getattr(usage, "prompt_tokens_details", None)
    if isinstance(details, dict):
        cached = details.get("cached_tokens")
        if (
            isinstance(cached, int)
            and not isinstance(cached, bool)
            and 0 <= cached <= usage.prompt_tokens
        ):
            return usage.prompt_tokens - cached
    return usage.prompt_tokens
