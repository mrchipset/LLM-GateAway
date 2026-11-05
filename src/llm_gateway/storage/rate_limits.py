from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
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
_BUCKET_WINDOW_SECONDS = 60.0
BucketScope = Literal["tenant", "key", "model"]
_REDIS_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local op = tonumber(ARGV[5])

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
if op == 0 then
  allowed = 1
elseif op == 2 then
  tokens = tokens - cost
  allowed = 1
elseif tokens >= cost then
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
    async def hit(self, *, tenant_id: UUID, limit: int, now: datetime) -> RateLimitResult:
        """Tenant RPM convenience; kept for callers that predate scoped buckets."""
        ...

    async def take(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
        cost: int = 1,
    ) -> RateLimitResult:
        """Refill and take ``cost`` tokens, or report how long until they exist."""
        ...

    async def consume(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
        cost: int,
    ) -> None:
        """Refill and take ``cost`` tokens even if it drives the bucket negative."""
        ...

    async def available(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
    ) -> float:
        """Refill and return the current token count without taking anything."""
        ...


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
    fixed-window counter allows). Buckets are keyed by ``(scope, key)``.
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def take(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
        cost: int = 1,
    ) -> RateLimitResult:
        _validate_hit(limit=limit, now=now)
        if cost < 1:
            raise ValueError("cost must be >= 1")
        async with self._lock:
            tokens, wait = self._refill(scope, key, limit, now)
            if tokens >= cost:
                tokens -= cost
                allowed, wait = True, 0.0
            else:
                allowed = False
            self._buckets[(scope, key)] = (tokens, now.timestamp())
        return RateLimitResult(
            allowed=allowed,
            remaining=max(math.floor(tokens), 0),
            retry_after_seconds=wait,
        )

    async def consume(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
        cost: int,
    ) -> None:
        _validate_hit(limit=limit, now=now)
        if cost < 0:
            raise ValueError("cost must be >= 0")
        async with self._lock:
            tokens, _ = self._refill(scope, key, limit, now)
            self._buckets[(scope, key)] = (tokens - cost, now.timestamp())

    async def available(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
    ) -> float:
        _validate_hit(limit=limit, now=now)
        async with self._lock:
            tokens, _ = self._refill(scope, key, limit, now)
            self._buckets[(scope, key)] = (tokens, now.timestamp())
        return tokens

    def _refill(
        self,
        scope: str,
        key: str,
        limit: int,
        now: datetime,
    ) -> tuple[float, float]:
        rate = limit / _BUCKET_WINDOW_SECONDS
        current = now.timestamp()
        tokens, stored = self._buckets.get((scope, key), (float(limit), current))
        if current < stored:
            current = stored
        refilled = min(float(limit), tokens + (current - stored) * rate)
        wait = 0.0 if refilled >= 1.0 else (1.0 - refilled) / rate
        return refilled, wait

    async def hit(self, *, tenant_id: UUID, limit: int, now: datetime) -> RateLimitResult:
        """Tenant RPM convenience used by the service layer before scopes existed."""
        return await self.take(scope="tenant", key=str(tenant_id), limit=limit, now=now)


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
        self._script = client.register_script(_REDIS_SCRIPT)

    async def take(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
        cost: int = 1,
    ) -> RateLimitResult:
        _validate_hit(limit=limit, now=now)
        if cost < 1:
            raise ValueError("cost must be >= 1")
        allowed, remaining, wait_ms = await self._run(scope, key, limit, now, cost, op=1)
        return RateLimitResult(
            allowed=bool(allowed),
            remaining=max(remaining, 0),
            retry_after_seconds=max(wait_ms, 0) / 1000.0,
        )

    async def consume(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
        cost: int,
    ) -> None:
        _validate_hit(limit=limit, now=now)
        if cost < 0:
            raise ValueError("cost must be >= 0")
        await self._run(scope, key, limit, now, cost, op=2)

    async def available(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
    ) -> float:
        _validate_hit(limit=limit, now=now)
        _, remaining, _ = await self._run(scope, key, limit, now, 1, op=0)
        return float(remaining)

    async def hit(self, *, tenant_id: UUID, limit: int, now: datetime) -> RateLimitResult:
        return await self.take(scope="tenant", key=str(tenant_id), limit=limit, now=now)

    async def _run(
        self,
        scope: str,
        key: str,
        limit: int,
        now: datetime,
        cost: int,
        *,
        op: int,
    ) -> tuple[int, int, int]:
        bucket = f"{self._key_prefix}:{scope}:{key}"
        refill_per_ms = limit / (_BUCKET_WINDOW_SECONDS * 1000)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                raw = await self._script(
                    keys=[bucket],
                    args=[limit, refill_per_ms, int(now.timestamp() * 1000), cost, op],
                )
        except TimeoutError as exc:
            raise RateLimiterUnavailable("timeout") from exc
        except (RedisError, OSError) as exc:
            raise RateLimiterUnavailable("error") from exc
        return int(raw[0]), int(raw[1]), int(raw[2])


class SqlAlchemyRateLimiter:
    """PostgreSQL fixed-window counter backed by one atomic upsert statement.

    Single-process only: each process keeps its own window, so this is the
    ``storage`` backend used when Redis is not configured.
    """

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._local = InMemoryRateLimiter()

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

    async def take(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
        cost: int = 1,
    ) -> RateLimitResult:
        if scope == "tenant":
            return await self.hit(tenant_id=UUID(key), limit=limit, now=now)
        return await self._local.take(scope=scope, key=key, limit=limit, now=now, cost=cost)

    async def consume(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
        cost: int,
    ) -> None:
        await self._local.consume(scope=scope, key=key, limit=limit, now=now, cost=cost)

    async def available(
        self,
        *,
        scope: BucketScope,
        key: str,
        limit: int,
        now: datetime,
    ) -> float:
        return await self._local.available(scope=scope, key=key, limit=limit, now=now)
