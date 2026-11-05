from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx

from llm_gateway.auth.last_used import LastUsedSampler
from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.storage.memory import InMemoryApiKeyRepository
from support import FrozenClock, seed_api_key, seed_tenant

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_sampler_touches_once_per_interval() -> None:
    sampler = LastUsedSampler(interval_seconds=60)
    key_id = uuid4()

    assert sampler.should_touch(key_id, NOW) is True
    assert sampler.should_touch(key_id, NOW + timedelta(seconds=30)) is False
    assert sampler.should_touch(key_id, NOW + timedelta(seconds=61)) is True
    assert sampler.should_touch(uuid4(), NOW + timedelta(seconds=61)) is True


def test_zero_interval_touches_every_request() -> None:
    sampler = LastUsedSampler(interval_seconds=0)
    key_id = uuid4()

    assert sampler.should_touch(key_id, NOW) is True
    assert sampler.should_touch(key_id, NOW) is True


class CountingKeys(InMemoryApiKeyRepository):
    def __init__(self) -> None:
        super().__init__()
        self.touches = 0

    async def touch_last_used(self, key_id: UUID, used_at: datetime) -> None:
        self.touches += 1
        await super().touch_last_used(key_id, used_at)


async def test_requests_touch_the_key_once_per_sample_window(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container: Any = make_container(settings, clock=FrozenClock(NOW))
    keys = CountingKeys()
    container.api_keys = keys
    tenant = await seed_tenant(container)
    secret = await seed_api_key(container, tenant_id=tenant.id)

    async with make_client(settings, container) as client:
        headers = {"Authorization": f"Bearer {secret}"}
        first = await client.get("/v1/models", headers=headers)
        second = await client.get("/v1/models", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert keys.touches == 1
