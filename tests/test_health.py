from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx
import pytest

from llm_gateway import __version__
from llm_gateway.config import Settings
from llm_gateway.container import Container, ReadinessCheck

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]
ContainerFactory = Callable[..., Container]


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


async def test_readyz_reports_named_checks(
    settings: Settings,
    make_client: ClientFactory,
    make_container: ContainerFactory,
) -> None:
    async def storage_check() -> bool:
        return True

    container = make_container(
        settings,
        readiness_checks=(ReadinessCheck(name="storage", check=storage_check),),
    )

    async with make_client(settings, container) as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"storage": "ok"}}


async def test_readyz_is_unavailable_when_check_raises(
    settings: Settings,
    make_client: ClientFactory,
    make_container: ContainerFactory,
) -> None:
    async def failing_check() -> bool:
        raise RuntimeError("database unavailable at internal-host")

    container = make_container(
        settings,
        readiness_checks=(ReadinessCheck(name="database", check=failing_check),),
    )

    async with make_client(settings, container) as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "error"},
    }
    assert "database unavailable" not in response.text
    assert "internal-host" not in response.text


def test_duplicate_readiness_check_names_are_rejected(
    settings: Settings,
    make_container: ContainerFactory,
) -> None:
    async def first_check() -> bool:
        return True

    async def second_check() -> bool:
        return True

    with pytest.raises(ValueError, match="duplicate readiness check name"):
        make_container(
            settings,
            readiness_checks=(
                ReadinessCheck(name="database", check=first_check),
                ReadinessCheck(name="database", check=second_check),
            ),
        )
