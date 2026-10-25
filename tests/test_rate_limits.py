from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from llm_gateway.storage.rate_limits import InMemoryRateLimiter

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


async def test_in_memory_rate_limiter_allows_then_denies() -> None:
    limiter = InMemoryRateLimiter()
    tenant_id = uuid4()

    first = await limiter.hit(tenant_id=tenant_id, limit=2, now=NOW)
    second = await limiter.hit(tenant_id=tenant_id, limit=2, now=NOW)
    third = await limiter.hit(tenant_id=tenant_id, limit=2, now=NOW)

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0
    assert third.allowed is False
    assert third.remaining == 0
    assert 0 < third.retry_after_seconds <= 60


async def test_in_memory_rate_limiter_resets_on_new_window() -> None:
    limiter = InMemoryRateLimiter()
    tenant_id = uuid4()
    await limiter.hit(tenant_id=tenant_id, limit=2, now=NOW)
    await limiter.hit(tenant_id=tenant_id, limit=2, now=NOW)

    rolled = await limiter.hit(
        tenant_id=tenant_id,
        limit=2,
        now=NOW + timedelta(seconds=61),
    )

    assert rolled.allowed is True
    assert rolled.remaining == 1


async def test_in_memory_rate_limiter_isolates_tenants() -> None:
    limiter = InMemoryRateLimiter()
    tenant_a = uuid4()
    tenant_b = uuid4()
    await limiter.hit(tenant_id=tenant_a, limit=1, now=NOW)
    denied = await limiter.hit(tenant_id=tenant_a, limit=1, now=NOW)

    other = await limiter.hit(tenant_id=tenant_b, limit=1, now=NOW)

    assert denied.allowed is False
    assert other.allowed is True


@pytest.mark.parametrize("limit", [0, -1])
async def test_in_memory_rate_limiter_rejects_invalid_limit(limit: int) -> None:
    limiter = InMemoryRateLimiter()

    with pytest.raises(ValueError, match="limit must be >= 1"):
        await limiter.hit(tenant_id=uuid4(), limit=limit, now=NOW)


async def test_in_memory_rate_limiter_rejects_naive_now() -> None:
    limiter = InMemoryRateLimiter()

    with pytest.raises(ValueError, match="now must be timezone-aware"):
        await limiter.hit(
            tenant_id=uuid4(),
            limit=1,
            now=datetime(2026, 1, 1, 12, 0),  # noqa: DTZ001 - naive under test
        )


async def test_in_memory_rate_limiter_ignores_stale_clock_window() -> None:
    limiter = InMemoryRateLimiter()
    tenant_id = uuid4()

    first = await limiter.hit(tenant_id=tenant_id, limit=1, now=NOW)
    newer = await limiter.hit(
        tenant_id=tenant_id,
        limit=1,
        now=NOW + timedelta(seconds=61),
    )
    stale = await limiter.hit(
        tenant_id=tenant_id,
        limit=1,
        now=NOW + timedelta(seconds=30),
    )
    still_stored = await limiter.hit(
        tenant_id=tenant_id,
        limit=1,
        now=NOW + timedelta(seconds=62),
    )

    assert first.allowed is True
    assert newer.allowed is True
    assert stale.allowed is False
    assert still_stored.allowed is False
    assert 0 <= stale.retry_after_seconds <= 60
