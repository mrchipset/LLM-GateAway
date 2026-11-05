from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.providers.base import ProviderName
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Usage,
)
from support import FrozenClock, seed_api_key, seed_model, seed_tenant

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
MODEL_ID = "limited-model"
PROMPT_TOKENS = 10
COMPLETION_TOKENS = 5
TOTAL_TOKENS = PROMPT_TOKENS + COMPLETION_TOKENS


class FixedUsageProvider:
    name = ProviderName.FAKE

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        self.calls += 1
        return ChatCompletionResponse(
            id="chatcmpl-limited",
            created=1,
            model=upstream_model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=Usage.model_validate(
                {
                    "prompt_tokens": PROMPT_TOKENS,
                    "completion_tokens": COMPLETION_TOKENS,
                    "total_tokens": TOTAL_TOKENS,
                }
            ),
        )

    def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        raise NotImplementedError("streaming is not used in rate limit tests")

    async def aclose(self) -> None:
        return None


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


async def _chat(client: httpx.AsyncClient, secret: str) -> httpx.Response:
    return await client.post(
        "/v1/chat/completions",
        headers=_auth(secret),
        json={"model": MODEL_ID, "messages": [{"role": "user", "content": "hello"}]},
    )


async def _stack(
    make_container: Callable[..., Container],
    settings: Settings,
    *,
    tenant: dict[str, Any] | None = None,
    key: dict[str, Any] | None = None,
    model: dict[str, Any] | None = None,
) -> tuple[Container, FixedUsageProvider, str, Any]:
    provider = FixedUsageProvider()
    container = make_container(
        settings,
        clock=FrozenClock(NOW),
        providers=ProviderRegistry({ProviderName.FAKE: provider}),
    )
    await seed_model(container, model_id=MODEL_ID, **(model or {}))
    tenant_record = await seed_tenant(container, name="rate-limit-tenant", **(tenant or {}))
    secret = await seed_api_key(container, tenant_id=tenant_record.id, **(key or {}))
    return container, provider, secret, tenant_record


async def test_key_request_limit_blocks_the_second_call(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret, _ = await _stack(
        make_container, settings, key={"requests_per_minute": 1}
    )

    async with make_client(settings, container) as client:
        first = await _chat(client, secret)
        second = await _chat(client, secret)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert int(second.headers["Retry-After"]) >= 1
    assert provider.calls == 1


async def test_model_request_limit_blocks_the_second_call(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret, _ = await _stack(
        make_container,
        settings,
        model={"requests_per_minute": 1},
    )

    async with make_client(settings, container) as client:
        first = await _chat(client, secret)
        second = await _chat(client, secret)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert provider.calls == 1


async def test_tenant_token_limit_is_settled_after_the_response(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret, tenant = await _stack(
        make_container,
        settings,
        tenant={"tokens_per_minute": 20},
    )

    async with make_client(settings, container) as client:
        first = await _chat(client, secret)
        second = await _chat(client, secret)
        third = await _chat(client, secret)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "token_rate_limited"
    assert provider.calls == 2

    remaining = await container.rate_limiter.available(
        scope="tenant",
        key=f"{tenant.id}:tpm",
        limit=20,
        now=NOW,
    )
    assert remaining == pytest.approx(20 - 2 * TOTAL_TOKENS)


async def test_no_configured_limits_admits_every_request(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret, _ = await _stack(make_container, settings)

    async with make_client(settings, container) as client:
        responses = [await _chat(client, secret) for _ in range(3)]

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert provider.calls == 3
