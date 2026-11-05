from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

import httpx

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
MODEL_ID = "capability-model"


class CountingProvider:
    name = ProviderName.FAKE

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        self.calls += 1
        return ChatCompletionResponse(
            id="chatcmpl-cap",
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
                {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
            ),
        )

    def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        raise NotImplementedError("streaming is rejected before the provider in these tests")

    async def aclose(self) -> None:
        return None


async def _stack(
    make_container: Callable[..., Container],
    settings: Settings,
    *,
    model: dict[str, Any],
) -> tuple[Container, CountingProvider, str]:
    provider = CountingProvider()
    container = make_container(
        settings,
        clock=FrozenClock(NOW),
        providers=ProviderRegistry({ProviderName.FAKE: provider}),
    )
    await seed_model(container, model_id=MODEL_ID, **model)
    tenant = await seed_tenant(container, name="capability-tenant")
    secret = await seed_api_key(container, tenant_id=tenant.id)
    return container, provider, secret


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": "hello"}],
    }
    body.update(overrides)
    return body


async def test_max_tokens_above_the_model_limit_is_rejected_before_upstream(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret = await _stack(
        make_container,
        settings,
        model={"max_output_tokens": 64},
    )

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {secret}"},
            json=_body(max_tokens=128),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "request_limit_exceeded"
    assert response.json()["error"]["param"] == "max_tokens"
    assert provider.calls == 0


async def test_tools_are_rejected_when_the_model_does_not_support_them(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret = await _stack(
        make_container,
        settings,
        model={"supports_tools": False},
    )

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {secret}"},
            json=_body(
                tools=[
                    {
                        "type": "function",
                        "function": {"name": "lookup", "parameters": {}},
                    }
                ]
            ),
        )

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "tools"
    assert provider.calls == 0


async def test_streaming_is_rejected_when_the_model_does_not_support_it(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret = await _stack(
        make_container,
        settings,
        model={"supports_streaming": False},
    )

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {secret}"},
            json=_body(stream=True),
        )

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "stream"
    assert provider.calls == 0


async def test_capabilities_allow_a_request_within_bounds(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret = await _stack(
        make_container,
        settings,
        model={"max_output_tokens": 64, "context_window": 4096},
    )

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {secret}"},
            json=_body(max_tokens=64, tools=[]),
        )

    assert response.status_code == 200
    assert provider.calls == 1
