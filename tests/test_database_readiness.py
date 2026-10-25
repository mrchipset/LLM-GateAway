from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from llm_gateway.clock import SystemClock
from llm_gateway.config import Environment, Settings, StorageBackend
from llm_gateway.container import Container, ReadinessCheck
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.storage.db import Database


def _unreachable_database(settings: Settings) -> Database:
    """Build a Database whose DSN points at a closed loopback port.

    Connection refusal is immediate and requires no external service, so this
    stays deterministic while exercising the real failure path.
    """
    unreachable = Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": settings.master_key.get_secret_value(),
            "storage_backend": StorageBackend.POSTGRES,
            "database_url": "postgresql+asyncpg://user:pass@127.0.0.1:1/gateway",
            "connect_timeout_seconds": 0.5,
            "request_timeout_seconds": 1.0,
        }
    )
    return Database.from_settings(unreachable)


async def test_ping_returns_false_and_warns_once_when_database_is_unreachable(
    settings: Settings,
    caplog: Any,
) -> None:
    database = _unreachable_database(settings)
    try:
        with caplog.at_level(logging.WARNING, logger="llm_gateway.storage.db"):
            first = await database.ping()
            second = await database.ping()
    finally:
        await database.aclose()

    assert first is False
    assert second is False
    failures = [
        record
        for record in caplog.records
        if record.name == "llm_gateway.storage.db" and "database ping failed" in record.getMessage()
    ]
    assert len(failures) == 1, "a persistent outage must not log on every probe"


async def test_readyz_returns_503_when_database_is_unreachable(
    settings: Settings,
    make_client: Callable[..., Any],
) -> None:
    database = _unreachable_database(settings)
    container = Container(
        settings=settings,
        clock=SystemClock(),
        api_keys=database.api_keys,
        models=database.models,
        tenants=database.tenants,
        usage=database.usage,
        providers=ProviderRegistry({}),
        readiness_checks=(ReadinessCheck(name="database", check=database.ping),),
        database=database,
    )

    async with make_client(settings, container) as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"database": "error"}}
