from __future__ import annotations

from random import Random

import pytest

from llm_gateway.providers.retry import RetryPolicy


def test_jitter_stays_within_cap_for_seeded_random() -> None:
    policy = RetryPolicy(base_delay_seconds=2.0, max_delay_seconds=64.0)
    rng = Random(1234)  # noqa: S311 - deterministic jitter test

    for retry_number in range(1, 7):
        cap = min(64.0, 2.0 * 2 ** (retry_number - 1))
        delay = policy.delay_for_attempt(retry_number, rng)
        assert 0 <= delay <= cap, f"delay {delay} outside [0, {cap}] for retry {retry_number}"


def test_cap_doubles_with_each_retry() -> None:
    policy = RetryPolicy(base_delay_seconds=1.5, max_delay_seconds=1000.0)
    rng = Random(99)  # noqa: S311 - deterministic jitter test

    caps = [min(1000.0, 1.5 * 2 ** (retry_number - 1)) for retry_number in range(1, 5)]
    delays = [policy.delay_for_attempt(retry_number, rng) for retry_number in range(1, 5)]

    for delay, cap in zip(delays, caps, strict=True):
        assert delay <= cap
    assert caps == [1.5, 3.0, 6.0, 12.0]


def test_cap_is_clamped_at_max_delay() -> None:
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=4.0)
    rng = Random(7)  # noqa: S311 - deterministic jitter test

    delay = policy.delay_for_attempt(10, rng)

    assert 0 <= delay <= 4.0


def test_retry_number_zero_is_rejected() -> None:
    policy = RetryPolicy()

    with pytest.raises(ValueError, match="retry_number"):
        policy.delay_for_attempt(0, Random(0))  # noqa: S311 - deterministic jitter test


def test_max_attempts_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)


def test_non_positive_base_delay_is_rejected() -> None:
    with pytest.raises(ValueError, match="base_delay_seconds"):
        RetryPolicy(base_delay_seconds=0)


def test_max_delay_below_base_delay_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_delay_seconds"):
        RetryPolicy(base_delay_seconds=2.0, max_delay_seconds=1.0)
