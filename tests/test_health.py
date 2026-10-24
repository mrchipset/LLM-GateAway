from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from llm_gateway import __version__
from llm_gateway.app import create_app
from llm_gateway.clock import SystemClock
from llm_gateway.config import Settings
from llm_gateway.container import Container


@asynccontextmanager
async def _client_for(
    settings: Settings,
    container: Container,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings=settings, container=container)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client


async def test_healthz_returns_status_and_version(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_readyz_is_ok_without_checks_in_memory_mode(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {}}


async def test_readyz_reports_named_checks(settings: Settings) -> None:
    async def storage_check() -> tuple[str, bool]:
        return ("storage", True)

    container = Container(
        settings=settings,
        clock=SystemClock(),
        readiness_checks=(storage_check,),
    )

    async with _client_for(settings, container) as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"storage": "ok"}}


async def test_readyz_is_unavailable_when_check_raises(
    settings: Settings,
) -> None:
    async def failing_check() -> tuple[str, bool]:
        raise RuntimeError("database unavailable at internal-host")

    container = Container(
        settings=settings,
        clock=SystemClock(),
        readiness_checks=(failing_check,),
    )

    async with _client_for(settings, container) as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"failing_check": "error"},
    }
    assert "database unavailable" not in response.text
    assert "internal-host" not in response.text
