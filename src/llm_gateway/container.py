from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Request

from llm_gateway.clock import Clock, SystemClock
from llm_gateway.config import Settings, StorageBackend
from llm_gateway.providers.factory import build_providers
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.storage.db import Database
from llm_gateway.storage.memory import InMemoryApiKeyRepository, InMemoryModelRepository
from llm_gateway.storage.repositories import ApiKeyRepository, ModelRepository


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
    providers: ProviderRegistry
    readiness_checks: tuple[ReadinessCheck, ...] = ()
    database: Database | None = None

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
            if self.database is not None:
                await self.database.aclose()


def get_container(request: Request) -> Container:
    container = request.app.state.container
    if not isinstance(container, Container):
        raise RuntimeError("application container is not configured")
    return container


def build_container(settings: Settings) -> Container:
    clock = SystemClock()
    providers = build_providers(settings, clock=clock)

    if settings.storage_backend is StorageBackend.POSTGRES:
        database = Database.from_settings(settings)
        return Container(
            settings=settings,
            clock=clock,
            api_keys=database.api_keys,
            models=database.models,
            providers=providers,
            readiness_checks=(ReadinessCheck(name="database", check=database.ping),),
            database=database,
        )

    return Container(
        settings=settings,
        clock=clock,
        api_keys=InMemoryApiKeyRepository(),
        models=InMemoryModelRepository(),
        providers=providers,
    )
