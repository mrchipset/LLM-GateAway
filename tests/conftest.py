from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest

from llm_gateway.app import create_app
from llm_gateway.clock import Clock, SystemClock
from llm_gateway.config import Environment, Settings
from llm_gateway.container import Container, ReadinessCheck
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.storage.memory import InMemoryApiKeyRepository, InMemoryModelRepository

TEST_MASTER_KEY = "test-master-key-0123456789abcdef"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": TEST_MASTER_KEY,
        }
    )


def make_container(
    settings: Settings,
    *,
    readiness_checks: tuple[ReadinessCheck, ...] = (),
    providers: ProviderRegistry | None = None,
    clock: Clock | None = None,
) -> Container:
    return Container(
        settings=settings,
        clock=clock if clock is not None else SystemClock(),
        api_keys=InMemoryApiKeyRepository(),
        models=InMemoryModelRepository(),
        providers=providers if providers is not None else ProviderRegistry({}),
        readiness_checks=readiness_checks,
    )


@pytest.fixture(name="make_container")
def _make_container_fixture() -> Callable[..., Container]:
    return make_container


@asynccontextmanager
async def make_client(
    settings: Settings,
    container: Container | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings=settings, container=container)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client,
    ):
        yield client


@pytest.fixture(name="make_client")
def _make_client_fixture() -> Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]:
    return make_client


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(settings) as test_client:
        yield test_client
