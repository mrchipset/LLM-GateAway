from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from llm_gateway.config import Settings
from llm_gateway.storage.rate_limits import RateLimiter, SqlAlchemyRateLimiter
from llm_gateway.storage.repositories import (
    ApiKeyRepository,
    ModelRepository,
    TenantRepository,
    UsageRepository,
)
from llm_gateway.storage.sql import (
    SqlAlchemyApiKeyRepository,
    SqlAlchemyModelRepository,
    SqlAlchemyTenantRepository,
    SqlAlchemyUsageRepository,
)

logger = logging.getLogger(__name__)


class Database:
    """Async engine plus the PostgreSQL-backed repository implementations.

    The engine and repositories live for the lifetime of the instance. Call
    :meth:`aclose` during application shutdown to release pooled connections.
    """

    def __init__(self, *, engine: AsyncEngine, connect_timeout_seconds: float = 10.0) -> None:
        self._engine = engine
        self._connect_timeout_seconds = connect_timeout_seconds
        self._ping_failure_logged = False
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False
        )
        self._api_keys = SqlAlchemyApiKeyRepository(session_factory=self._session_factory)
        self._models = SqlAlchemyModelRepository(session_factory=self._session_factory)
        self._tenants = SqlAlchemyTenantRepository(session_factory=self._session_factory)
        self._usage = SqlAlchemyUsageRepository(session_factory=self._session_factory)
        self._rate_limiter = SqlAlchemyRateLimiter(session_factory=self._session_factory)

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        if not settings.database_url:
            raise ValueError("database_url is required for the postgres storage backend")
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_timeout=settings.connect_timeout_seconds,
            pool_recycle=1800,
            connect_args={"timeout": settings.connect_timeout_seconds},
        )
        return cls(engine=engine, connect_timeout_seconds=settings.connect_timeout_seconds)

    @property
    def api_keys(self) -> ApiKeyRepository:
        return self._api_keys

    @property
    def models(self) -> ModelRepository:
        return self._models

    @property
    def tenants(self) -> TenantRepository:
        return self._tenants

    @property
    def usage(self) -> UsageRepository:
        return self._usage

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    async def ping(self) -> bool:
        try:
            async with asyncio.timeout(self._connect_timeout_seconds):
                async with self._session_factory() as session:
                    await session.execute(text("SELECT 1"))
        except Exception as exc:
            if not self._ping_failure_logged:
                self._ping_failure_logged = True
                logger.warning("database ping failed (%s)", type(exc).__name__)
            return False
        self._ping_failure_logged = False
        return True

    async def aclose(self) -> None:
        await self._engine.dispose()
