from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from llm_gateway.providers.throughput import (
    THROUGHPUT_WINDOW_SECONDS,
    compute_throughput,
    recent_throughput,
    record_stream_throughput,
    reset_throughput_window,
)
from llm_gateway.schemas.chat import Usage


@pytest.fixture(autouse=True)
def _clean_window() -> Iterator[None]:
    reset_throughput_window()
    yield
    reset_throughput_window()


def _usage(*, prompt: int = 1000, completion: int = 101, **extra: object) -> Usage:
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        **extra,
    )


def test_derives_prefill_and_decode_rates_from_stream_timing() -> None:
    result = compute_throughput(usage=_usage(), ttft_seconds=0.5, decode_seconds=2.0)

    assert result.prefill_tokens_per_second == pytest.approx(2000.0)
    assert result.decode_tokens_per_second == pytest.approx(50.0)


def test_cached_prompt_tokens_are_excluded_from_prefill() -> None:
    usage = _usage(prompt_tokens_details={"cached_tokens": 400})

    result = compute_throughput(usage=usage, ttft_seconds=0.5, decode_seconds=2.0)

    assert result.prefill_tokens_per_second == pytest.approx(1200.0)


def test_cached_tokens_above_prompt_are_ignored() -> None:
    usage = _usage(prompt_tokens_details={"cached_tokens": 5000})

    result = compute_throughput(usage=usage, ttft_seconds=0.5, decode_seconds=2.0)

    assert result.prefill_tokens_per_second == pytest.approx(2000.0)


def test_single_completion_token_has_no_decode_rate() -> None:
    result = compute_throughput(usage=_usage(completion=1), ttft_seconds=0.5, decode_seconds=2.0)

    assert result.prefill_tokens_per_second == pytest.approx(2000.0)
    assert result.decode_tokens_per_second is None


def test_zero_time_to_first_token_skips_prefill() -> None:
    result = compute_throughput(usage=_usage(), ttft_seconds=0.0, decode_seconds=2.0)

    assert result.prefill_tokens_per_second is None
    assert result.decode_tokens_per_second == pytest.approx(50.0)


def test_non_positive_decode_window_skips_decode() -> None:
    result = compute_throughput(usage=_usage(), ttft_seconds=0.5, decode_seconds=0.0)

    assert result.prefill_tokens_per_second == pytest.approx(2000.0)
    assert result.decode_tokens_per_second is None


def test_missing_usage_skips_both_rates() -> None:
    result = compute_throughput(usage=None, ttft_seconds=0.5, decode_seconds=2.0)

    assert result.prefill_tokens_per_second is None
    assert result.decode_tokens_per_second is None


def _record(*, ttft: float, decode: float, model: str = "chat") -> None:
    record_stream_throughput(
        provider="deepseek",
        model=model,
        span=None,
        usage=_usage(),
        ttft_seconds=ttft,
        decode_seconds=decode,
    )


def test_window_reports_percentiles_per_model() -> None:
    _record(ttft=0.5, decode=2.0)  # prefill 2000, decode 50
    _record(ttft=1 / 3, decode=1.0)  # prefill 3000, decode 100
    _record(ttft=1.0, decode=4.0)  # prefill 1000, decode 25

    stats = recent_throughput()

    assert len(stats) == 1
    item = stats[0]
    assert item.samples == 3
    assert item.prefill_tokens_per_second_p50 == pytest.approx(2000.0)
    assert item.prefill_tokens_per_second_p95 == pytest.approx(3000.0)
    assert item.decode_tokens_per_second_p50 == pytest.approx(50.0)
    assert item.decode_tokens_per_second_p95 == pytest.approx(100.0)
    assert item.last_observed_at is not None


def test_window_shares_between_models() -> None:
    _record(ttft=0.5, decode=2.0, model="alpha")
    _record(ttft=0.5, decode=2.0, model="beta")

    stats = recent_throughput()

    assert [item.model for item in stats] == ["alpha", "beta"]
    assert all(item.samples == 1 for item in stats)


def test_window_drops_samples_outside_the_retention_period() -> None:
    _record(ttft=0.5, decode=2.0)

    assert recent_throughput(now=time.time() + THROUGHPUT_WINDOW_SECONDS + 1) == []


def test_samples_without_rates_are_not_remembered() -> None:
    record_stream_throughput(
        provider="deepseek",
        model="chat",
        span=None,
        usage=None,
        ttft_seconds=0.5,
        decode_seconds=2.0,
    )

    assert recent_throughput() == []
