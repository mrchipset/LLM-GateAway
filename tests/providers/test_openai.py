from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from random import Random
from typing import cast

import httpx
import pytest
import respx

from llm_gateway.providers.base import (
    ProviderConnectionError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from llm_gateway.providers.openai import OpenAIProvider
from llm_gateway.providers.retry import RetryPolicy
from llm_gateway.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionRequest,
)

API_KEY = "sk-test-secret-value"
BASE_URL = "https://upstream.test/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"


class MaxUniformRandom(Random):
    """Deterministic RNG that always returns the upper jitter bound."""

    def uniform(self, a: float, b: float) -> float:
        return b


class RecordingSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        await asyncio.sleep(0)


class RecordingByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def make_provider(
    *,
    client: httpx.AsyncClient | None = None,
    sleeper: RecordingSleeper | None = None,
    max_attempts: int = 3,
) -> OpenAIProvider:
    return OpenAIProvider(
        api_key=API_KEY,
        base_url=BASE_URL,
        timeout=httpx.Timeout(5.0),
        retry_policy=RetryPolicy(max_attempts=max_attempts),
        client=client,
        sleeper=sleeper if sleeper is not None else RecordingSleeper(),
        rng=MaxUniformRandom(0),
    )


def make_request() -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(
        {
            "model": "public-model",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.2,
            "logprobs": True,
        }
    )


def completion_body() -> dict[str, object]:
    return {
        "id": "chatcmpl-upstream",
        "object": "chat.completion",
        "created": 100,
        "model": "gpt-upstream",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hi there"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
    }


def chunk_payload(
    content: str | None = None,
    *,
    role: str | None = None,
    finish_reason: str | None = None,
) -> dict[str, object]:
    delta: dict[str, object] = {}
    if role is not None:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    return {
        "id": "chatcmpl-up",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def sse_event(payload: object, *, line_end: str = "\n") -> str:
    return f"data: {json.dumps(payload)}{line_end}{line_end}"


async def collect_chunks(
    provider: OpenAIProvider, request: ChatCompletionRequest
) -> list[ChatCompletionChunk]:
    return [
        chunk async for chunk in provider.stream(upstream_model="gpt-upstream", request=request)
    ]


async def test_complete_forwards_request_fields_and_maps_response() -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.post(CHAT_URL).mock(return_value=httpx.Response(200, json=completion_body()))
        provider = make_provider()

        response = await provider.complete(upstream_model="gpt-upstream", request=make_request())

        assert len(route.calls) == 1
        sent = json.loads(route.calls[-1].request.content)
        assert sent["model"] == "gpt-upstream"
        assert sent["stream"] is False
        assert sent["temperature"] == 0.2
        assert sent["logprobs"] is True
        assert route.calls[-1].request.headers["Authorization"] == f"Bearer {API_KEY}"

    assert response.id == "chatcmpl-upstream"
    assert response.model == "gpt-upstream"
    assert response.choices[0].message.content == "hi there"
    assert response.choices[0].finish_reason == "stop"
    assert response.usage is not None
    assert response.usage.total_tokens == 4


async def test_complete_maps_401_without_retrying() -> None:
    sleeper = RecordingSleeper()
    with respx.mock(assert_all_called=False) as router:
        route = router.post(CHAT_URL).mock(
            return_value=httpx.Response(401, json={"error": {"message": "invalid key"}})
        )
        provider = make_provider(sleeper=sleeper)

        with pytest.raises(ProviderUpstreamError) as info:
            await provider.complete(upstream_model="gpt-upstream", request=make_request())

        assert len(route.calls) == 1
    assert info.value.status_code == 401
    assert "invalid key" in info.value.message
    assert sleeper.delays == []
    assert API_KEY not in str(info.value)


async def test_complete_retries_500_then_succeeds() -> None:
    sleeper = RecordingSleeper()
    with respx.mock(assert_all_called=False) as router:
        route = router.post(CHAT_URL).mock(
            side_effect=[
                httpx.Response(500, json={"error": {"message": "server error"}}),
                httpx.Response(200, json=completion_body()),
            ]
        )
        provider = make_provider(sleeper=sleeper)

        response = await provider.complete(upstream_model="gpt-upstream", request=make_request())

        assert len(route.calls) == 2
    assert response.id == "chatcmpl-upstream"
    assert len(sleeper.delays) == 1
    assert 0 < sleeper.delays[0] <= 0.5


async def test_complete_retries_429_then_succeeds() -> None:
    sleeper = RecordingSleeper()
    with respx.mock(assert_all_called=False) as router:
        route = router.post(CHAT_URL).mock(
            side_effect=[
                httpx.Response(429, json={"error": {"message": "rate limited"}}),
                httpx.Response(200, json=completion_body()),
            ]
        )
        provider = make_provider(sleeper=sleeper)

        response = await provider.complete(upstream_model="gpt-upstream", request=make_request())

        assert len(route.calls) == 2
    assert response.id == "chatcmpl-upstream"
    assert len(sleeper.delays) == 1


async def test_complete_exhausted_retries_raise_last_error() -> None:
    sleeper = RecordingSleeper()
    with respx.mock(assert_all_called=False) as router:
        route = router.post(CHAT_URL).mock(
            return_value=httpx.Response(500, json={"error": {"message": "still broken"}})
        )
        provider = make_provider(sleeper=sleeper, max_attempts=2)

        with pytest.raises(ProviderUpstreamError) as info:
            await provider.complete(upstream_model="gpt-upstream", request=make_request())

        assert len(route.calls) == 2
    assert info.value.status_code == 500
    assert len(sleeper.delays) == 1


async def test_complete_maps_connect_error() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.post(CHAT_URL).mock(side_effect=httpx.ConnectError("boom"))
        provider = make_provider(max_attempts=1)

        with pytest.raises(ProviderConnectionError) as info:
            await provider.complete(upstream_model="gpt-upstream", request=make_request())

    assert API_KEY not in str(info.value)


async def test_complete_maps_timeout() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.post(CHAT_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        provider = make_provider(max_attempts=1)

        with pytest.raises(ProviderTimeoutError):
            await provider.complete(upstream_model="gpt-upstream", request=make_request())


async def test_complete_maps_malformed_json_without_leaking_payload() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.post(CHAT_URL).mock(return_value=httpx.Response(200, text="{not json"))
        provider = make_provider()

        with pytest.raises(ProviderResponseError) as info:
            await provider.complete(upstream_model="gpt-upstream", request=make_request())

    assert "not json" not in str(info.value)
    assert API_KEY not in str(info.value)


async def test_complete_does_not_close_injected_client() -> None:
    client = httpx.AsyncClient()
    try:
        provider = make_provider(client=client)
        await provider.aclose()
        assert not client.is_closed
    finally:
        await client.aclose()


async def test_aclose_is_idempotent_for_owned_client() -> None:
    provider = make_provider()

    await provider.aclose()
    await provider.aclose()


async def test_stream_parses_split_events_and_multiple_events_per_chunk() -> None:
    first = chunk_payload("", role="assistant")
    second = chunk_payload("hello")
    raw = (sse_event(first) + sse_event(second) + "data: [DONE]\n\n").encode()
    end_first = raw.index(b"\n\n") + 2
    end_second = raw.index(b"\n\n", end_first) + 2
    stream = RecordingByteStream([raw[:10], raw[10:end_second], raw[end_second:]])

    with respx.mock(assert_all_called=False) as router:
        route = router.post(CHAT_URL).mock(return_value=httpx.Response(200, stream=stream))
        provider = make_provider()

        chunks = await collect_chunks(provider, make_request())

        assert len(route.calls) == 1
        sent = json.loads(route.calls[-1].request.content)
        assert sent["stream"] is True

    contents = [chunk.choices[0].delta.content for chunk in chunks]
    assert contents == ["", "hello"]
    assert stream.closed


async def test_stream_tolerates_crlf_line_endings() -> None:
    first = chunk_payload("", role="assistant")
    second = chunk_payload("hi", finish_reason="stop")
    raw = (
        sse_event(first, line_end="\r\n")
        + sse_event(second, line_end="\r\n")
        + "data: [DONE]\r\n\r\n"
    ).encode()
    stream = RecordingByteStream([raw])

    with respx.mock(assert_all_called=False) as router:
        router.post(CHAT_URL).mock(return_value=httpx.Response(200, stream=stream))
        provider = make_provider()

        chunks = await collect_chunks(provider, make_request())

    assert [chunk.choices[0].delta.content for chunk in chunks] == ["", "hi"]
    assert chunks[-1].choices[0].finish_reason == "stop"
    assert stream.closed


async def test_stream_stops_at_done_and_ignores_following_data() -> None:
    first = chunk_payload("", role="assistant")
    raw = (sse_event(first) + "data: [DONE]\n\n" + "data: {this is not json}\n\n").encode()
    stream = RecordingByteStream([raw])

    with respx.mock(assert_all_called=False) as router:
        router.post(CHAT_URL).mock(return_value=httpx.Response(200, stream=stream))
        provider = make_provider()

        chunks = await collect_chunks(provider, make_request())

    assert len(chunks) == 1
    assert stream.closed


async def test_stream_ignores_comments_and_non_data_fields() -> None:
    first = chunk_payload("", role="assistant")
    second = chunk_payload("hello")
    raw = (
        ": keep-alive\n"
        "event: message\n"
        "id: 42\n"
        "retry: 1000\n\n" + sse_event(first) + sse_event(second) + "data: [DONE]\n\n"
    ).encode()
    stream = RecordingByteStream([raw])

    with respx.mock(assert_all_called=False) as router:
        router.post(CHAT_URL).mock(return_value=httpx.Response(200, stream=stream))
        provider = make_provider()

        chunks = await collect_chunks(provider, make_request())

    assert [chunk.choices[0].delta.content for chunk in chunks] == ["", "hello"]


async def test_stream_parses_trailing_data_without_newline() -> None:
    first = chunk_payload("", role="assistant")
    raw = f"data: {json.dumps(first)}".encode()
    stream = RecordingByteStream([raw])

    with respx.mock(assert_all_called=False) as router:
        router.post(CHAT_URL).mock(return_value=httpx.Response(200, stream=stream))
        provider = make_provider()

        chunks = await collect_chunks(provider, make_request())

    assert len(chunks) == 1
    assert chunks[0].choices[0].delta.role == "assistant"
    assert stream.closed


async def test_stream_error_frame_raises_without_retry() -> None:
    stream = RecordingByteStream(
        [f"data: {json.dumps({'error': {'message': 'upstream exploded'}})}\n\n".encode()]
    )

    with respx.mock(assert_all_called=False) as router:
        route = router.post(CHAT_URL).mock(return_value=httpx.Response(200, stream=stream))
        provider = make_provider()

        with pytest.raises(ProviderUpstreamError) as info:
            await collect_chunks(provider, make_request())

        assert len(route.calls) == 1

    assert info.value.status_code is None
    assert "upstream exploded" in info.value.message
    assert stream.closed


async def test_stream_invalid_json_raises_response_error() -> None:
    stream = RecordingByteStream([b"data: {not json\n\n"])

    with respx.mock(assert_all_called=False) as router:
        router.post(CHAT_URL).mock(return_value=httpx.Response(200, stream=stream))
        provider = make_provider()

        with pytest.raises(ProviderResponseError):
            await collect_chunks(provider, make_request())

    assert stream.closed


async def test_stream_early_close_releases_response() -> None:
    first = chunk_payload("", role="assistant")
    second = chunk_payload("hello")
    raw = (sse_event(first) + sse_event(second) + "data: [DONE]\n\n").encode()
    stream = RecordingByteStream([raw])

    with respx.mock(assert_all_called=False) as router:
        router.post(CHAT_URL).mock(return_value=httpx.Response(200, stream=stream))
        provider = make_provider()

        generator = cast(
            AsyncGenerator[ChatCompletionChunk, None],
            provider.stream(upstream_model="gpt-upstream", request=make_request()),
        )
        chunk = await anext(generator)
        assert chunk.choices[0].delta.role == "assistant"
        await generator.aclose()

    assert stream.closed
