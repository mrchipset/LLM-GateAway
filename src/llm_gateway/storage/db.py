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
    AdminAuditRepository,
    AdminSessionRepository,
    AdminUserRepository,
    ApiKeyRepository,
    AuditRepository,
    LoginThrottle,
    ModelDeploymentRepository,
    ModelPriceRepository,
    ModelRepository,
    TenantRepository,
    UsageRepository,
)
from llm_gateway.storage.sql import (
    SqlAlchemyAdminAuditRepository,
    SqlAlchemyAdminSessionRepository,
    SqlAlchemyAdminUserRepository,
    SqlAlchemyApiKeyRepository,
    SqlAlchemyAuditRepository,
    SqlAlchemyLoginThrottle,
    SqlAlchemyModelDeploymentRepository,
    SqlAlchemyModelPriceRepository,
    SqlAlchemyModelRepository,
    SqlAlchemyTenantRepository,
    SqlAlchemyUsageRepository,
)

logger = logging.getLogger(__name__)


def _connect_args(settings: Settings) -> dict[str, object]:
    """asyncpg connect arguments, including the server-side statement timeout.

    ``statement_timeout`` is a server setting rather than a client option, so it
    travels in ``server_settings``. Zero disables it and leaves the server default.
    """
    args: dict[str, object] = {"timeout": settings.connect_timeout_seconds}
    if settings.database_statement_timeout_ms > 0:
        args["server_settings"] = {
            "statement_timeout": f"{settings.database_statement_timeout_ms}ms"
        }
    return args


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
        self._prices = SqlAlchemyModelPriceRepository(session_factory=self._session_factory)
        self._tenants = SqlAlchemyTenantRepository(session_factory=self._session_factory)
        self._usage = SqlAlchemyUsageRepository(session_factory=self._session_factory)
        self._audit = SqlAlchemyAuditRepository(session_factory=self._session_factory)
        self._rate_limiter = SqlAlchemyRateLimiter(session_factory=self._session_factory)
        self._admins = SqlAlchemyAdminUserRepository(session_factory=self._session_factory)
        self._deployments = SqlAlchemyModelDeploymentRepository(
            session_factory=self._session_factory
        )
        self._admin_sessions = SqlAlchemyAdminSessionRepository(
            session_factory=self._session_factory
        )
        self._admin_audit = SqlAlchemyAdminAuditRepository(session_factory=self._session_factory)
        self._login_throttle = SqlAlchemyLoginThrottle(session_factory=self._session_factory)

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        if not settings.database_url:
            raise ValueError("database_url is required for the postgres storage backend")
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
            pool_recycle=1800,
            connect_args=_connect_args(settings),
        )
        return cls(engine=engine, connect_timeout_seconds=settings.connect_timeout_seconds)

    @property
    def api_keys(self) -> ApiKeyRepository:
        return self._api_keys

    @property
    def models(self) -> ModelRepository:
        return self._models

    @property
    def prices(self) -> ModelPriceRepository:
        return self._prices

    @property
    def tenants(self) -> TenantRepository:
        return self._tenants

    @property
    def usage(self) -> UsageRepository:
        return self._usage

    @property
    def audit(self) -> AuditRepository:
        return self._audit

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    @property
    def deployments(self) -> ModelDeploymentRepository:
        return self._deployments

    @property
    def admins(self) -> AdminUserRepository:
        return self._admins

    @property
    def admin_sessions(self) -> AdminSessionRepository:
        return self._admin_sessions

    @property
    def admin_audit(self) -> AdminAuditRepository:
        return self._admin_audit

    @property
    def login_throttle(self) -> LoginThrottle:
        return self._login_throttle

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
