"""Streaming idle-timeout behaviour of ``OpenAIProvider``.

A stream that stops producing bytes must surface a real timeout error rather
than looking like a completed answer, while a slow but still-producing upstream
must never be interrupted.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from typing import cast

import httpx
import pytest

from llm_gateway.providers.base import ProviderTimeoutError
from llm_gateway.providers.openai import OpenAIProvider
from llm_gateway.providers.retry import RetryPolicy
from llm_gateway.schemas.chat import ChatCompletionChunk, ChatCompletionRequest

API_KEY = "sk-test-secret-value"
BASE_URL = "https://upstream.test/v1"


class FakeStreamingResponse:
    """Minimal stand-in for an ``httpx.Response`` used by ``stream()``."""

    status_code = 200
    headers = httpx.Headers({"content-type": "text/event-stream"})

    def __init__(
        self,
        chunks: list[bytes],
        *,
        gap_seconds: float = 0.0,
        block_after_chunks: bool = False,
    ) -> None:
        self._chunks = chunks
        self._gap_seconds = gap_seconds
        self._block_after_chunks = block_after_chunks
        self.closed = False

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for index, chunk in enumerate(self._chunks):
            if index > 0 and self._gap_seconds > 0:
                await asyncio.sleep(self._gap_seconds)
            yield chunk
        if self._block_after_chunks:
            await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


class StubProvider(OpenAIProvider):
    """Provider whose transport is replaced by a fake streaming response."""

    def __init__(self, response: FakeStreamingResponse, *, idle_timeout_seconds: float) -> None:
        super().__init__(
            api_key=API_KEY,
            base_url=BASE_URL,
            timeout=httpx.Timeout(5.0),
            retry_policy=RetryPolicy(max_attempts=1),
            stream_idle_timeout_seconds=idle_timeout_seconds,
        )
        self._stub_response = response

    async def _send_stream(
        self, payload: dict[str, object], *, headers: dict[str, str]
    ) -> httpx.Response:
        return cast(httpx.Response, self._stub_response)


def make_request() -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(
        {
            "model": "public-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
    )


def chunk_payload(content: str) -> dict[str, object]:
    return {
        "id": "chatcmpl-up",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
    }


def sse_event(payload: object) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


async def test_idle_stream_raises_timeout_and_closes_response() -> None:
    sentinel = "SENSITIVE-PAYLOAD-TOKEN"
    response = FakeStreamingResponse(
        [sse_event(chunk_payload(sentinel))],
        block_after_chunks=True,
    )
    provider = StubProvider(response, idle_timeout_seconds=0.05)
    generator = cast(
        AsyncGenerator[ChatCompletionChunk, None],
        provider.stream(upstream_model="gpt-upstream", request=make_request()),
    )
    try:
        first = await anext(generator)
        assert first.choices[0].delta.content == sentinel

        with pytest.raises(ProviderTimeoutError) as info:
            await anext(generator)

        assert "0.05" in str(info.value)
        assert sentinel not in str(info.value)
        assert "idle" in str(info.value)
    finally:
        await generator.aclose()
        await provider.aclose()

    assert response.closed


async def test_disabled_idle_timeout_streams_to_completion() -> None:
    response = FakeStreamingResponse(
        [
            sse_event(chunk_payload("hello")),
            b"data: [DONE]\n\n",
        ]
    )
    provider = StubProvider(response, idle_timeout_seconds=0.0)
    try:
        chunks = [
            chunk
            async for chunk in provider.stream(
                upstream_model="gpt-upstream", request=make_request()
            )
        ]
    finally:
        await provider.aclose()

    assert [chunk.choices[0].delta.content for chunk in chunks] == ["hello"]
    assert response.closed


async def test_gap_shorter_than_idle_timeout_is_not_interrupted() -> None:
    # A few milliseconds of real time keeps the test fast and deterministic
    # while staying well below the idle timeout under test.
    response = FakeStreamingResponse(
        [
            sse_event(chunk_payload("first")),
            sse_event(chunk_payload("second")),
            b"data: [DONE]\n\n",
        ],
        gap_seconds=0.01,
    )
    provider = StubProvider(response, idle_timeout_seconds=0.2)
    try:
        chunks = [
            chunk
            async for chunk in provider.stream(
                upstream_model="gpt-upstream", request=make_request()
            )
        ]
    finally:
        await provider.aclose()

    assert [chunk.choices[0].delta.content for chunk in chunks] == ["first", "second"]
    assert response.closed
