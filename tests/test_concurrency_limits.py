from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from llm_gateway.api.inference import _stream_sse
from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.providers.base import ProviderName
from llm_gateway.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatDelta,
    Usage,
)
from llm_gateway.services.chat import ChatStream
from llm_gateway.services.limits import acquire_concurrency, release_concurrency
from llm_gateway.services.usage import UsageContext, UsageRecorder
from llm_gateway.storage.rate_limits import InMemoryRateLimiter
from llm_gateway.storage.repositories import ApiKeyRecord
from support import FrozenClock, seed_tenant

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
MODEL_ID = "concurrency-model"


def _chunks() -> list[ChatCompletionChunk]:
    return [
        ChatCompletionChunk(
            id="c1",
            created=1,
            model=MODEL_ID,
            choices=[ChatCompletionChunkChoice(index=0, delta=ChatDelta(content="hi"))],
        ),
        ChatCompletionChunk(
            id="c1",
            created=1,
            model=MODEL_ID,
            choices=[ChatCompletionChunkChoice(index=0, finish_reason="stop")],
            usage=Usage.model_validate(
                {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
            ),
        ),
    ]


async def _upstream() -> AsyncGenerator[ChatCompletionChunk, None]:
    yield _chunks()[1]


def _key(key_id: UUID, tenant_id: UUID) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=key_id,
        tenant_id=tenant_id,
        name="lease-key",
        key_hash="0" * 64,
        key_prefix="sk-gw-000000",
        created_at=NOW,
    )


def _stream() -> ChatStream:
    chunks = _chunks()
    return ChatStream(
        first_chunk=chunks[0],
        model_id=MODEL_ID,
        provider=ProviderName.FAKE,
        client_wants_usage=False,
        usage=None,
        upstream=_upstream(),
    )


async def test_in_memory_leases_bound_and_release() -> None:
    limiter = InMemoryRateLimiter()

    assert await limiter.acquire(scope="tenant", key="one", limit=1, ttl_seconds=60) is True
    assert await limiter.acquire(scope="tenant", key="one", limit=1, ttl_seconds=60) is False

    await limiter.release(scope="tenant", key="one")
    await limiter.release(scope="tenant", key="one")

    assert await limiter.acquire(scope="tenant", key="one", limit=1, ttl_seconds=60) is True


async def test_tenant_lease_blocks_a_second_request_until_released(
    settings: Settings,
    make_container: Callable[..., Container],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))
    tenant = await seed_tenant(container, name="lease-tenant", max_concurrent_requests=1)
    key_id = uuid4()

    leases = await acquire_concurrency(container, tenant=tenant, key_record=_key(key_id, tenant.id))
    assert len(leases) == 1

    with pytest.raises(ApiError) as info:
        await acquire_concurrency(container, tenant=tenant, key_record=_key(key_id, tenant.id))
    assert info.value.status_code == 429
    assert info.value.code is ApiErrorCode.CONCURRENCY_LIMITED

    await release_concurrency(container, leases)
    second = await acquire_concurrency(container, tenant=tenant, key_record=_key(key_id, tenant.id))
    assert len(second) == 1


async def test_streaming_response_releases_the_lease_when_it_finishes(
    settings: Settings,
    make_container: Callable[..., Container],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))
    tenant = await seed_tenant(container, name="lease-stream", max_concurrent_requests=1)
    key_id = uuid4()
    leases = await acquire_concurrency(container, tenant=tenant, key_record=_key(key_id, tenant.id))

    frames = [
        frame
        async for frame in _stream_sse(
            _stream(),
            recorder=UsageRecorder(
                repository=container.usage,
                clock=container.clock,
                rate_limiter=container.rate_limiter,
            ),
            context=UsageContext(
                request_id="req-lease",
                tenant_id=tenant.id,
                api_key_id=key_id,
                model_id=MODEL_ID,
                provider=ProviderName.FAKE,
            ),
            container=container,
            leases=leases,
        )
    ]

    assert b"[DONE]" in frames[-1]
    again = await acquire_concurrency(container, tenant=tenant, key_record=_key(key_id, tenant.id))
    assert len(again) == 1
