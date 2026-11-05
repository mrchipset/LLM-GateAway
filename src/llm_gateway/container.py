from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import Request
from redis.asyncio import Redis

from llm_gateway.auth.last_used import LastUsedSampler
from llm_gateway.clock import Clock, SystemClock
from llm_gateway.config import RateLimitBackend, Settings, StorageBackend
from llm_gateway.lifecycle import InFlightTracker
from llm_gateway.metrics import configure_metrics, shutdown_metrics
from llm_gateway.providers.factory import build_providers
from llm_gateway.providers.pool import ProviderPool
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.services.oidc import OIDCService
from llm_gateway.services.routing import ModelRouter
from llm_gateway.storage.cooldowns import (
    DeploymentHealth,
    InMemoryDeploymentHealth,
    RedisDeploymentHealth,
)
from llm_gateway.storage.db import Database
from llm_gateway.storage.memory import (
    InMemoryAdminAuditRepository,
    InMemoryAdminSessionRepository,
    InMemoryAdminUserRepository,
    InMemoryApiKeyRepository,
    InMemoryAuditRepository,
    InMemoryLoginThrottle,
    InMemoryModelDeploymentRepository,
    InMemoryModelPriceRepository,
    InMemoryModelRepository,
    InMemoryTenantRepository,
    InMemoryUsageRepository,
)
from llm_gateway.storage.rate_limits import InMemoryRateLimiter, RateLimiter, RedisRateLimiter
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
from llm_gateway.telemetry import Telemetry, configure_telemetry


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    name: str
    check: Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    checks: dict[str, str]


@dataclass(slots=True)
class Container:
    """Everything the request path depends on, built once at startup."""

    settings: Settings
    clock: Clock
    api_keys: ApiKeyRepository
    models: ModelRepository
    prices: ModelPriceRepository
    tenants: TenantRepository
    usage: UsageRepository
    rate_limiter: RateLimiter
    providers: ProviderRegistry
    readiness_checks: tuple[ReadinessCheck, ...] = ()
    database: Database | None = None
    audit: AuditRepository = field(default_factory=InMemoryAuditRepository)
    deployments: ModelDeploymentRepository = field(
        default_factory=InMemoryModelDeploymentRepository
    )
    admins: AdminUserRepository = field(default_factory=InMemoryAdminUserRepository)
    admin_sessions: AdminSessionRepository = field(default_factory=InMemoryAdminSessionRepository)
    admin_audit: AdminAuditRepository = field(default_factory=InMemoryAdminAuditRepository)
    login_throttle: LoginThrottle = field(default_factory=InMemoryLoginThrottle)
    router: ModelRouter | None = None
    telemetry: Telemetry | None = None
    inflight: InFlightTracker = field(default_factory=InFlightTracker)
    last_used_sampler: LastUsedSampler = field(default_factory=LastUsedSampler)
    redis_client: Redis | None = None
    oidc: OIDCService | None = None

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for item in self.readiness_checks:
            if item.name in seen:
                raise ValueError(f"duplicate readiness check name: {item.name}")
            seen.add(item.name)

    async def check_readiness(self) -> ReadinessReport:
        results = await asyncio.gather(
            *(item.check() for item in self.readiness_checks),
            return_exceptions=True,
        )

        checks: dict[str, str] = {}
        for item, result in zip(self.readiness_checks, results, strict=True):
            if isinstance(result, BaseException):
                checks[item.name] = "error"
                continue
            checks[item.name] = "ok" if result else "error"

        return ReadinessReport(
            ready=all(status == "ok" for status in checks.values()),
            checks=checks,
        )

    async def aclose(self) -> None:
        try:
            await self.providers.aclose()
        finally:
            try:
                if self.oidc is not None:
                    await self.oidc.aclose()
                if self.redis_client is not None:
                    await self.redis_client.aclose()
            finally:
                if self.database is not None:
                    await self.database.aclose()
                if self.telemetry is not None:
                    self.telemetry.shutdown()
                shutdown_metrics()


def get_container(request: Request) -> Container:
    container = request.app.state.container
    if not isinstance(container, Container):
        raise RuntimeError("application container is not configured")
    return container


def build_container(settings: Settings, *, telemetry: Telemetry | None = None) -> Container:
    clock = SystemClock()
    configure_metrics(settings)
    resolved_telemetry = telemetry if telemetry is not None else configure_telemetry(settings)
    providers = build_providers(settings, clock=clock, tracer=resolved_telemetry.tracer)
    pool = ProviderPool(
        settings=settings,
        providers=providers,
        tracer=resolved_telemetry.tracer,
    )

    if settings.storage_backend is StorageBackend.POSTGRES:
        database = Database.from_settings(settings)
        container = Container(
            settings=settings,
            clock=clock,
            api_keys=database.api_keys,
            models=database.models,
            prices=database.prices,
            deployments=database.deployments,
            tenants=database.tenants,
            usage=database.usage,
            audit=database.audit,
            rate_limiter=database.rate_limiter,
            admins=database.admins,
            admin_sessions=database.admin_sessions,
            admin_audit=database.admin_audit,
            login_throttle=database.login_throttle,
            providers=providers,
            readiness_checks=(ReadinessCheck(name="database", check=database.ping),),
            database=database,
            telemetry=resolved_telemetry,
        )
    else:
        container = Container(
            settings=settings,
            clock=clock,
            api_keys=InMemoryApiKeyRepository(),
            models=InMemoryModelRepository(),
            prices=InMemoryModelPriceRepository(),
            deployments=InMemoryModelDeploymentRepository(),
            tenants=InMemoryTenantRepository(),
            usage=InMemoryUsageRepository(),
            audit=InMemoryAuditRepository(),
            rate_limiter=InMemoryRateLimiter(),
            providers=providers,
            telemetry=resolved_telemetry,
        )

    if settings.rate_limit_backend is RateLimitBackend.REDIS:
        if settings.redis_url is None:  # guarded by Settings validation
            raise ValueError("redis_url is required when rate_limit_backend is redis")
        redis_client = Redis.from_url(settings.redis_url)
        container.rate_limiter = RedisRateLimiter(
            client=redis_client,
            timeout_seconds=settings.rate_limit_redis_timeout_seconds,
        )
        container.redis_client = redis_client
        if not settings.rate_limit_fail_open:
            # Fail-closed only: when the limiter is down every request is rejected,
            # so the instance must also stop advertising readiness.
            async def _ping_redis() -> bool:
                return bool(await redis_client.ping())

            container.readiness_checks = (
                *container.readiness_checks,
                ReadinessCheck(name="rate_limiter", check=_ping_redis),
            )

    health: DeploymentHealth
    if container.redis_client is not None:
        health = RedisDeploymentHealth(
            client=container.redis_client,
            threshold=settings.route_failure_threshold,
            cooldown_seconds=settings.route_cooldown_seconds,
            timeout_seconds=settings.rate_limit_redis_timeout_seconds,
        )
    else:
        health = InMemoryDeploymentHealth(
            threshold=settings.route_failure_threshold,
            cooldown_seconds=settings.route_cooldown_seconds,
        )
    container.router = ModelRouter(
        deployments=container.deployments,
        pool=pool,
        health=health,
        clock=clock,
        tracer=resolved_telemetry.tracer,
        max_attempts=settings.route_max_attempts,
    )
    container.last_used_sampler = LastUsedSampler(
        interval_seconds=settings.last_used_sample_seconds,
    )
    if settings.oidc_enabled:
        container.oidc = OIDCService(settings=settings)
    return container
