from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest

from llm_gateway.app import create_app
from llm_gateway.config import Environment, Settings
from llm_gateway.container import Container

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
