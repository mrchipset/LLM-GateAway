from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from llm_gateway.storage.rate_limits import RateLimiterUnavailable, RedisRateLimiter

REDIS_URL = os.environ.get("GATEWAY_TEST_REDIS_URL")
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not REDIS_URL,
        reason="GATEWAY_TEST_REDIS_URL is not set",
    ),
]


def _url() -> str:
    if not REDIS_URL:
        raise RuntimeError("GATEWAY_TEST_REDIS_URL is not set")
    return REDIS_URL


@pytest.fixture
async def client() -> AsyncIterator[Redis]:
    redis = Redis.from_url(_url())
    try:
        yield redis
    finally:
        await redis.aclose()


async def test_two_replicas_share_one_bucket(client: Redis) -> None:
    prefix = f"test:{uuid4()}"
    replica_a = RedisRateLimiter(client=client, key_prefix=prefix)
    replica_b = RedisRateLimiter(client=client, key_prefix=prefix)
    tenant_id = uuid4()

    first = await replica_a.hit(tenant_id=tenant_id, limit=2, now=NOW)
    second = await replica_b.hit(tenant_id=tenant_id, limit=2, now=NOW)
    denied = await replica_b.hit(tenant_id=tenant_id, limit=2, now=NOW)

    assert first.allowed is True
    assert second.allowed is True
    assert denied.allowed is False
    assert denied.retry_after_seconds > 0


async def test_bucket_refills_from_elapsed_time(client: Redis) -> None:
    limiter = RedisRateLimiter(client=client, key_prefix=f"test:{uuid4()}")
    tenant_id = uuid4()

    for _ in range(60):
        await limiter.hit(tenant_id=tenant_id, limit=60, now=NOW)

    later = NOW + timedelta(seconds=2)
    admitted = 0
    for _ in range(5):
        result = await limiter.hit(tenant_id=tenant_id, limit=60, now=later)
        admitted += 1 if result.allowed else 0

    assert admitted == 2


async def test_a_backwards_clock_never_refills_the_bucket(client: Redis) -> None:
    limiter = RedisRateLimiter(client=client, key_prefix=f"test:{uuid4()}")
    tenant_id = uuid4()
    await limiter.hit(tenant_id=tenant_id, limit=2, now=NOW)
    await limiter.hit(tenant_id=tenant_id, limit=2, now=NOW)

    denied = await limiter.hit(
        tenant_id=tenant_id,
        limit=2,
        now=NOW - timedelta(minutes=5),
    )

    assert denied.allowed is False


async def test_unreachable_redis_raises_a_typed_error() -> None:
    unreachable = Redis.from_url("redis://127.0.0.1:1", socket_connect_timeout=0.2)
    limiter = RedisRateLimiter(client=unreachable, timeout_seconds=0.5)
    try:
        with pytest.raises(RateLimiterUnavailable) as info:
            await limiter.hit(tenant_id=uuid4(), limit=10, now=NOW)
    finally:
        await unreachable.aclose()

    assert info.value.reason == "error"


async def test_concurrency_leases_are_shared_and_expire(client: Redis) -> None:
    prefix = f"test:{uuid4()}"
    replica_a = RedisRateLimiter(client=client, key_prefix=prefix)
    replica_b = RedisRateLimiter(client=client, key_prefix=prefix)

    assert await replica_a.acquire(scope="tenant", key="lease", limit=1, ttl_seconds=1) is True
    assert await replica_b.acquire(scope="tenant", key="lease", limit=1, ttl_seconds=1) is False

    await replica_b.release(scope="tenant", key="lease")
    assert await replica_a.acquire(scope="tenant", key="lease", limit=1, ttl_seconds=1) is True

    # A crashed process leaves the slot behind; the TTL must reclaim it.
    await asyncio.sleep(1.1)
    assert await replica_b.acquire(scope="tenant", key="lease", limit=1, ttl_seconds=1) is True
