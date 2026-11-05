"""Behaviour of the Anthropic Messages adapter.

The adapter must translate between the gateway's OpenAI-compatible contract and
Anthropic's Messages wire format without leaking provider details inward. These
tests use an injected ``httpx.MockTransport`` so no network is involved.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from typing import cast

import httpx
import pytest

from llm_gateway.providers.anthropic import AnthropicProvider
from llm_gateway.providers.base import (
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from llm_gateway.providers.retry import RetryPolicy
from llm_gateway.schemas.chat import ChatCompletionChunk, ChatCompletionRequest

API_KEY = "sk-ant-test-secret-value"
BASE_URL = "https://anthropic.test"
MESSAGES_URL = f"{BASE_URL}/v1/messages"
DEFAULT_MAX_TOKENS = 256


class NoopSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


class RecordingByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class BlockingByteStream(httpx.AsyncByteStream):
    """Yields its chunks, then blocks forever until the read is cancelled."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


def make_provider(
    *,
    client: httpx.AsyncClient,
    sleeper: NoopSleeper | None = None,
    max_attempts: int = 3,
    idle_timeout_seconds: float = 0.0,
) -> AnthropicProvider:
    return AnthropicProvider(
        api_key=API_KEY,
        base_url=BASE_URL,
        version="2023-06-01",
        default_max_tokens=DEFAULT_MAX_TOKENS,
        timeout=httpx.Timeout(5.0),
        retry_policy=RetryPolicy(max_attempts=max_attempts),
        client=client,
        sleeper=sleeper if sleeper is not None else NoopSleeper(),
        stream_idle_timeout_seconds=idle_timeout_seconds,
    )


def make_request(**overrides: object) -> ChatCompletionRequest:
    payload: dict[str, object] = {
        "model": "public-model",
        "messages": [{"role": "user", "content": "hello"}],
    }
    payload.update(overrides)
    return ChatCompletionRequest.model_validate(payload)


def completion_body(
    *,
    content: list[dict[str, object]] | None = None,
    stop_reason: str | None = "end_turn",
    usage: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": "msg_upstream",
        "type": "message",
        "role": "assistant",
        "model": "claude-upstream",
        "content": content if content is not None else [{"type": "text", "text": "hi"}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage if usage is not None else {"input_tokens": 2, "output_tokens": 3},
    }


def sse(event: str, payload: object) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


def _tool_argument_delta(chunk: ChatCompletionChunk) -> str:
    tool_calls = chunk.choices[0].delta.tool_calls
    assert tool_calls is not None
    function = tool_calls[0].get("function")
    assert isinstance(function, dict)
    arguments = function.get("arguments")
    assert isinstance(arguments, str)
    return arguments


async def test_complete_translates_system_stop_tools_and_max_tokens() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=completion_body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = make_provider(client=client)
        request = make_request(
            messages=[
                {"role": "system", "content": "Be brief."},
                {"role": "system", "content": "Use JSON."},
                {"role": "user", "content": "hello"},
            ],
            temperature=0.3,
            top_p=0.9,
            stop="END",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "Look something up.",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                        },
                    },
                }
            ],
            tool_choice="auto",
        )

        await provider.complete(upstream_model="claude-sonnet", request=request)

    assert len(captured) == 1
    sent = json.loads(captured[0].content)
    assert str(captured[0].url) == MESSAGES_URL
    assert captured[0].headers["x-api-key"] == API_KEY
    assert captured[0].headers["anthropic-version"] == "2023-06-01"
    assert sent["model"] == "claude-sonnet"
    assert sent["stream"] is False
    assert sent["system"] == "Be brief.\n\nUse JSON."
    assert sent["messages"] == [{"role": "user", "content": "hello"}]
    assert sent["max_tokens"] == DEFAULT_MAX_TOKENS
    assert sent["stop_sequences"] == ["END"]
    assert sent["temperature"] == 0.3
    assert sent["top_p"] == 0.9
    assert sent["tools"] == [
        {
            "name": "lookup",
            "description": "Look something up.",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
        }
    ]
    assert sent["tool_choice"] == {"type": "auto"}
    assert "presence_penalty" not in sent


async def test_complete_uses_max_completion_tokens_when_max_tokens_is_absent() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=completion_body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = make_provider(client=client)
        request = make_request(max_completion_tokens=64)

        await provider.complete(upstream_model="claude-sonnet", request=request)

    sent = json.loads(captured[0].content)
    assert sent["max_tokens"] == 64


async def test_complete_maps_text_and_tool_use_blocks_to_openai_response() -> None:
    body = completion_body(
        content=[
            {"type": "text", "text": "Let me check."},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "lookup",
                "input": {"city": "Paris", "limit": 2},
            },
        ],
        stop_reason="tool_use",
        usage={"input_tokens": 12, "output_tokens": 5, "cache_read_input_tokens": 4},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = make_provider(client=client)
        response = await provider.complete(upstream_model="claude-sonnet", request=make_request())

    assert response.id == "msg_upstream"
    assert response.model == "public-model"
    assert response.choices[0].message.content == "Let me check."
    tool_calls = response.choices[0].message.tool_calls
    assert tool_calls is not None
    assert tool_calls == [
        {
            "id": "toolu_1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"city":"Paris","limit":2}'},
        }
    ]
    assert response.choices[0].finish_reason == "tool_calls"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 5
    assert response.usage.total_tokens == 17
    dumped = response.model_dump()
    assert dumped["usage"]["prompt_tokens_details"]["cached_tokens"] == 4


async def test_stream_maps_text_tool_arguments_and_final_usage() -> None:
    raw = b"".join(
        [
            sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "model": "claude-upstream",
                        "usage": {"input_tokens": 10, "cache_read_input_tokens": 3},
                    },
                },
            ),
            sse(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello"},
                },
            ),
            sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
            sse(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "lookup",
                        "input": {},
                    },
                },
            ),
            sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": '{"city":'},
                },
            ),
            sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": '"Paris"}'},
                },
            ),
            sse("content_block_stop", {"type": "content_block_stop", "index": 1}),
            sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 7},
                },
            ),
            sse("message_stop", {"type": "message_stop"}),
        ]
    )
    # Split inside an event so the parser has to buffer partial lines.
    split_at = raw.index(b"message_start") + 5
    stream = RecordingByteStream([raw[:split_at], raw[split_at:]])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = make_provider(client=client)
        chunks = [
            chunk
            async for chunk in provider.stream(
                upstream_model="claude-sonnet", request=make_request()
            )
        ]

    assert [chunk.id for chunk in chunks] == ["msg_1"] * len(chunks)
    assert all(chunk.model == "public-model" for chunk in chunks)

    assert chunks[0].choices[0].delta.content == "Hello"
    assert chunks[0].choices[0].delta.tool_calls is None

    start = chunks[1].choices[0].delta.tool_calls
    assert start == [
        {
            "index": 0,
            "id": "toolu_1",
            "type": "function",
            "function": {"name": "lookup", "arguments": ""},
        }
    ]

    argument_deltas = [_tool_argument_delta(chunk) for chunk in chunks[2:4]]
    assert argument_deltas == ['{"city":', '"Paris"}']

    final = chunks[-1]
    assert final.choices[0].finish_reason == "tool_calls"
    assert final.usage is not None
    assert final.usage.prompt_tokens == 10
    assert final.usage.completion_tokens == 7
    assert final.usage.total_tokens == 17
    assert final.model_dump()["usage"]["prompt_tokens_details"]["cached_tokens"] == 3
    assert stream.closed


@pytest.mark.parametrize("status_code", [400, 429, 500])
async def test_complete_maps_api_errors_and_retries_only_retryable_statuses(
    status_code: int,
) -> None:
    calls: list[httpx.Request] = []
    sleeper = NoopSleeper()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                status_code,
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": "bad request"},
                },
            )
        return httpx.Response(200, json=completion_body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = make_provider(client=client, sleeper=sleeper, max_attempts=2)
        if status_code == 400:
            with pytest.raises(ProviderUpstreamError) as info:
                await provider.complete(upstream_model="claude-sonnet", request=make_request())
            assert info.value.status_code == 400
            assert "bad request" in info.value.message
            assert len(calls) == 1
            assert sleeper.delays == []
        else:
            response = await provider.complete(
                upstream_model="claude-sonnet", request=make_request()
            )
            assert response.id == "msg_upstream"
            assert len(calls) == 2
            assert len(sleeper.delays) == 1


async def test_idle_stream_raises_timeout_and_closes_response() -> None:
    stream = BlockingByteStream(
        [
            sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "usage": {"input_tokens": 1},
                    },
                },
            ),
            sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "hello"},
                },
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = make_provider(client=client, idle_timeout_seconds=0.05)
        generator = cast(
            AsyncGenerator[ChatCompletionChunk, None],
            provider.stream(upstream_model="claude-sonnet", request=make_request()),
        )

        first = await anext(generator)
        assert first.choices[0].delta.content == "hello"

        with pytest.raises(ProviderTimeoutError) as info:
            await anext(generator)

        assert "0.05" in str(info.value)
        assert "idle" in str(info.value)
        await generator.aclose()

    assert stream.closed
