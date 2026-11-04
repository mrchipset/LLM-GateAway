from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from llm_gateway.storage.repositories import UnknownTenantError
from llm_gateway.storage.sql import _is_foreign_key_violation
from llm_gateway.storage.tables import TenantRateLimitRow

_WINDOW_SECONDS = 60
_BURST_WINDOW_SECONDS = 60.0
_REDIS_TAKE_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local stored_ms = tonumber(data[2])
if tokens == nil or stored_ms == nil then
  tokens = capacity
  stored_ms = now_ms
end
-- A clock that moves backwards must not create tokens.
if now_ms < stored_ms then
  now_ms = stored_ms
end
tokens = math.min(capacity, tokens + (now_ms - stored_ms) * refill_per_ms)

local allowed = 0
local wait_ms = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  wait_ms = math.ceil((cost - tokens) / refill_per_ms)
end

redis.call('HSET', key, 'tokens', tokens, 'ts', now_ms)
redis.call('PEXPIRE', key, math.ceil(capacity / refill_per_ms) + 1000)
return {allowed, math.floor(tokens), wait_ms}
"""


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: float


class RateLimiterUnavailable(Exception):
    """The limiter backend could not answer; callers decide fail-open or fail-closed."""

    def __init__(self, reason: str) -> None:
        super().__init__("rate limiter backend is unavailable")
        self.reason = reason


class RateLimiter(Protocol):
    async def hit(self, *, tenant_id: UUID, limit: int, now: datetime) -> RateLimitResult: ...


def _validate_hit(*, limit: int, now: datetime) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be >= 1")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")


def _window_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(second=0, microsecond=0)


def _result(*, count: int, limit: int, window_start: datetime, now: datetime) -> RateLimitResult:
    window_end = window_start + timedelta(seconds=_WINDOW_SECONDS)
    return RateLimitResult(
        allowed=count <= limit,
        remaining=max(limit - count, 0),
        retry_after_seconds=min(
            max((window_end - now).total_seconds(), 0.0),
            float(_WINDOW_SECONDS),
        ),
    )


class InMemoryRateLimiter:
    """Process-local token bucket for tests and single-process dev.

    ``limit`` is the burst capacity and the per-minute refill rate, so two
    consecutive fixed windows cannot each admit a full batch (the 2x burst a
    fixed-window counter allows). The bucket is keyed by tenant only.
    """

    def __init__(self) -> None:
        self._buckets: dict[UUID, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def hit(self, *, tenant_id: UUID, limit: int, now: datetime) -> RateLimitResult:
        _validate_hit(limit=limit, now=now)
        rate = limit / _BURST_WINDOW_SECONDS
        current = now.timestamp()
        async with self._lock:
            tokens, stored = self._buckets.get(tenant_id, (float(limit), current))
            if current < stored:
                current = stored
            tokens = min(float(limit), tokens + (current - stored) * rate)
            if tokens >= 1.0:
                tokens -= 1.0
                allowed = True
                wait = 0.0
            else:
                allowed = False
                wait = (1.0 - tokens) / rate
            self._buckets[tenant_id] = (tokens, current)
        return RateLimitResult(
            allowed=allowed,
            remaining=math.floor(tokens),
            retry_after_seconds=wait,
        )


class RedisRateLimiter:
    """Shared token bucket in Redis, consistent across gateway processes.

    The whole refill-and-take runs inside one Lua script, so replicas cannot
    interleave between reading and writing the bucket. ``now`` comes from the
    injected clock; a backwards clock is clamped to the stored timestamp and
    therefore can only under-refill, never over-grant.
    """

    def __init__(
        self,
        *,
        client: Redis,
        key_prefix: str = "llm-gateway:rate",
        timeout_seconds: float = 0.2,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        self._client = client
        self._key_prefix = key_prefix
        self._timeout_seconds = timeout_seconds
        self._script = client.register_script(_REDIS_TAKE_SCRIPT)

    async def hit(self, *, tenant_id: UUID, limit: int, now: datetime) -> RateLimitResult:
        _validate_hit(limit=limit, now=now)
        key = f"{self._key_prefix}:tenant:{tenant_id}"
        now_ms = int(now.timestamp() * 1000)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                raw = await self._script(
                    keys=[key],
                    args=[limit, limit / (_BURST_WINDOW_SECONDS * 1000), now_ms, 1],
                )
        except TimeoutError as exc:
            raise RateLimiterUnavailable("timeout") from exc
        except (RedisError, OSError) as exc:
            raise RateLimiterUnavailable("error") from exc
        allowed, remaining, wait_ms = (int(value) for value in raw)
        return RateLimitResult(
            allowed=bool(allowed),
            remaining=max(remaining, 0),
            retry_after_seconds=max(wait_ms, 0) / 1000.0,
        )


class SqlAlchemyRateLimiter:
    """PostgreSQL fixed-window counter backed by one atomic upsert statement."""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def hit(self, *, tenant_id: UUID, limit: int, now: datetime) -> RateLimitResult:
        _validate_hit(limit=limit, now=now)
        window_start = _window_start(now)
        statement = pg_insert(TenantRateLimitRow).values(
            tenant_id=tenant_id,
            window_start=window_start,
            count=1,
        )
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[TenantRateLimitRow.tenant_id],
            set_={
                "count": case(
                    (
                        excluded.window_start > TenantRateLimitRow.window_start,
                        1,
                    ),
                    else_=TenantRateLimitRow.count + 1,
                ),
                "window_start": func.greatest(
                    TenantRateLimitRow.window_start,
                    excluded.window_start,
                ),
            },
        ).returning(TenantRateLimitRow.count, TenantRateLimitRow.window_start)
        try:
            async with self._session_factory() as session, session.begin():
                row = (await session.execute(statement)).one()
        except IntegrityError as exc:
            if _is_foreign_key_violation(exc):
                raise UnknownTenantError(tenant_id) from exc
            raise
        count, stored_window_start = row
        return _result(
            count=int(count),
            limit=limit,
            window_start=stored_window_start,
            now=now,
        )
