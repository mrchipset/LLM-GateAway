from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from llm_gateway.storage.repositories import UnknownTenantError
from llm_gateway.storage.sql import _is_foreign_key_violation
from llm_gateway.storage.tables import TenantRateLimitRow

_WINDOW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: float


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
    """Process-local fixed-window counter for tests and single-process dev."""

    def __init__(self) -> None:
        self._windows: dict[UUID, tuple[datetime, int]] = {}
        self._lock = asyncio.Lock()

    async def hit(self, *, tenant_id: UUID, limit: int, now: datetime) -> RateLimitResult:
        _validate_hit(limit=limit, now=now)
        window_start = _window_start(now)
        async with self._lock:
            current = self._windows.get(tenant_id)
            if current is None or window_start > current[0]:
                count = 1
                stored_window_start = window_start
            else:
                count = current[1] + 1
                stored_window_start = current[0]
            self._windows[tenant_id] = (stored_window_start, count)
        return _result(
            count=count,
            limit=limit,
            window_start=stored_window_start,
            now=now,
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
