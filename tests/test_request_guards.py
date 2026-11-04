from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

import httpx
import pytest

from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.providers.base import ProviderName
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.schemas.chat import ChatCompletionRequest
from llm_gateway.services.guards import (
    RequestLimits,
    enforce_chat_request_limits,
    limits_from_settings,
)
from support import CapturingUsageRepository, FrozenClock, seed_api_key, seed_model

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
MODEL_ID = "guarded-model"
LIMITS = RequestLimits(
    max_messages=3,
    max_prompt_chars=200,
    max_tokens_limit=64,
    max_tools=2,
)


def _request(**overrides: object) -> ChatCompletionRequest:
    body: dict[str, object] = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": "hello"}],
    }
    body.update(overrides)
    return ChatCompletionRequest.model_validate(body)


def _messages(count: int, content: str = "x") -> list[dict[str, object]]:
    return [{"role": "user", "content": content} for _ in range(count)]


def _assert_limit(error: ApiError, *, param: str) -> None:
    assert error.status_code == 400
    assert error.code is ApiErrorCode.REQUEST_LIMIT_EXCEEDED
    assert error.param == param


def test_messages_over_the_limit_are_rejected() -> None:
    with pytest.raises(ApiError) as info:
        enforce_chat_request_limits(_request(messages=_messages(4)), limits=LIMITS)

    _assert_limit(info.value, param="messages")


def test_prompt_character_budget_is_enforced() -> None:
    with pytest.raises(ApiError) as info:
        enforce_chat_request_limits(
            _request(messages=[{"role": "user", "content": "x" * 300}]),
            limits=LIMITS,
        )

    _assert_limit(info.value, param="messages")


def test_max_tokens_is_capped() -> None:
    with pytest.raises(ApiError) as info:
        enforce_chat_request_limits(_request(max_tokens=65), limits=LIMITS)

    _assert_limit(info.value, param="max_tokens")


def test_max_completion_tokens_wins_and_names_the_field() -> None:
    with pytest.raises(ApiError) as info:
        enforce_chat_request_limits(
            _request(max_tokens=1, max_completion_tokens=1000),
            limits=LIMITS,
        )

    _assert_limit(info.value, param="max_completion_tokens")


def test_tools_are_capped() -> None:
    tools = [
        {"type": "function", "function": {"name": f"tool-{index}", "parameters": {}}}
        for index in range(3)
    ]

    with pytest.raises(ApiError) as info:
        enforce_chat_request_limits(_request(tools=tools), limits=LIMITS)

    _assert_limit(info.value, param="tools")


def test_at_the_limit_is_allowed() -> None:
    enforce_chat_request_limits(
        _request(
            messages=_messages(3),
            max_tokens=64,
            tools=[
                {"type": "function", "function": {"name": "a", "parameters": {}}},
                {"type": "function", "function": {"name": "b", "parameters": {}}},
            ],
        ),
        limits=LIMITS,
    )


async def _setup(
    make_container: Callable[..., Container],
    settings: Settings,
) -> tuple[Container, CapturingUsageRepository, str]:
    usage = CapturingUsageRepository()
    clock = FrozenClock(NOW)
    container = make_container(
        settings,
        clock=clock,
        providers=ProviderRegistry({ProviderName.FAKE: FakeProvider(clock=clock)}),
        usage=usage,
    )
    await seed_model(container, model_id=MODEL_ID)
    secret = await seed_api_key(container)
    return container, usage, secret


async def test_api_rejects_oversized_max_tokens_without_calling_upstream(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    limited = settings.model_copy(update={"max_tokens_limit": 10})
    container, usage, secret = await _setup(make_container, limited)

    async with make_client(limited, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {secret}"},
            json={
                "model": MODEL_ID,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 100,
            },
        )

    assert response.status_code == 400
    body = response.json()["error"]
    assert body["code"] == "request_limit_exceeded"
    assert body["param"] == "max_tokens"
    assert body["request_id"] == response.headers["x-request-id"]
    assert usage.records == []


async def test_api_rejects_an_oversized_body_with_413(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    limited = settings.model_copy(update={"max_request_bytes": 1024})
    container, usage, secret = await _setup(make_container, limited)

    async with make_client(limited, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {secret}"},
            json={
                "model": MODEL_ID,
                "messages": [{"role": "user", "content": "x" * 4000}],
            },
        )

    assert response.status_code == 413
    body = response.json()["error"]
    assert body["code"] == "request_too_large"
    assert body["request_id"] == response.headers["x-request-id"]
    assert usage.records == []


def test_limits_follow_settings(settings: Settings) -> None:
    configured = settings.model_copy(
        update={
            "max_messages": 7,
            "max_prompt_chars": 900,
            "max_tokens_limit": 123,
            "max_tools": 4,
        }
    )

    assert limits_from_settings(configured) == RequestLimits(
        max_messages=7,
        max_prompt_chars=900,
        max_tokens_limit=123,
        max_tools=4,
    )
