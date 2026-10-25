from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx
import pytest

from llm_gateway.app import create_app
from llm_gateway.clock import SystemClock
from llm_gateway.config import Environment, Settings
from llm_gateway.container import Container
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.storage.memory import (
    InMemoryApiKeyRepository,
    InMemoryModelRepository,
    InMemoryTenantRepository,
    InMemoryUsageRepository,
)
from llm_gateway.storage.rate_limits import InMemoryRateLimiter

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


class _TrackingContainer(Container):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            settings=settings,
            clock=SystemClock(),
            api_keys=InMemoryApiKeyRepository(),
            models=InMemoryModelRepository(),
            tenants=InMemoryTenantRepository(),
            usage=InMemoryUsageRepository(),
            rate_limiter=InMemoryRateLimiter(),
            providers=ProviderRegistry({}),
        )
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


async def test_lifespan_closes_container_after_client_exit(
    settings: Settings,
    make_client: ClientFactory,
) -> None:
    container = _TrackingContainer(settings)

    async with make_client(settings, container) as client:
        response = await client.get("/healthz")
        assert response.status_code == 200
        assert container.closed is False

    assert container.closed is True


def test_create_app_rejects_mismatched_settings(
    settings: Settings,
    make_container: Callable[..., Container],
) -> None:
    other_settings = Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": "another-test-key-0123456789abcdef",
        }
    )
    container = make_container(other_settings)

    with pytest.raises(ValueError, match=r"container\.settings"):
        create_app(settings=settings, container=container)
