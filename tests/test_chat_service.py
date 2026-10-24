from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Literal, cast

import pytest

from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.providers.base import (
    ProviderConnectionError,
    ProviderError,
    ProviderName,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatDelta,
    ChatMessage,
)
from llm_gateway.services.chat import ChatService, ChatStream, map_provider_error
from llm_gateway.storage.memory import InMemoryModelRepository
from llm_gateway.storage.repositories import ModelConfig

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
PUBLIC_MODEL = "public-model"
UPSTREAM_MODEL = "upstream-model"


def make_request(model: str = PUBLIC_MODEL) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model=model,
        messages=[ChatMessage(role="user", content="hello")],
    )


def make_chunk(
    content: str | None = None,
    *,
    model: str = UPSTREAM_MODEL,
    role: Literal["system", "developer", "user", "assistant", "tool"] | None = None,
    finish_reason: str | None = None,
) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="chunk-1",
        created=1,
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatDelta(role=role, content=content),
                finish_reason=finish_reason,
            )
        ],
    )


class RecordingProvider:
    name = ProviderName.FAKE

    def __init__(
        self,
        *,
        chunks: list[ChatCompletionChunk] | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self.upstream_models: list[str] = []
        self.yielded = 0
        self.closed = 0
        self._chunks = chunks if chunks is not None else [make_chunk("hi")]
        self._stream_error = stream_error

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        self.upstream_models.append(upstream_model)
        return ChatCompletionResponse(
            id="completion-1",
            created=1,
            model=upstream_model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="hi"),
                    finish_reason="stop",
                )
            ],
        )

    def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        self.upstream_models.append(upstream_model)
        return self._stream()

    async def _stream(self) -> AsyncGenerator[ChatCompletionChunk, None]:
        try:
            if self._stream_error is not None:
                raise self._stream_error
            for chunk in self._chunks:
                self.yielded += 1
                yield chunk
        finally:
            self.closed += 1

    async def aclose(self) -> None:
        return None


async def make_service(
    provider: RecordingProvider,
    *,
    provider_name: ProviderName = ProviderName.FAKE,
    enabled: bool = True,
) -> ChatService:
    models = InMemoryModelRepository()
    await models.create_model(
        ModelConfig(
            id=PUBLIC_MODEL,
            provider=provider_name,
            upstream_model=UPSTREAM_MODEL,
            created_at=NOW,
            enabled=enabled,
        )
    )
    return ChatService(models=models, providers=ProviderRegistry({provider_name: provider}))


async def collect(stream: ChatStream) -> list[ChatCompletionChunk]:
    return [chunk async for chunk in stream.chunks()]


@pytest.mark.parametrize(
    (
        "exc",
        "expected_status",
        "expected_code",
        "expected_type",
        "expected_message",
    ),
    [
        (
            ProviderTimeoutError(),
            504,
            ApiErrorCode.UPSTREAM_TIMEOUT,
            "server_error",
            "Upstream provider timed out",
        ),
        (
            ProviderConnectionError(),
            502,
            ApiErrorCode.UPSTREAM_UNAVAILABLE,
            "server_error",
            "Upstream provider is unavailable",
        ),
        (
            ProviderResponseError(),
            502,
            ApiErrorCode.UPSTREAM_INVALID_RESPONSE,
            "server_error",
            "Upstream provider returned an invalid response",
        ),
        (
            ProviderUpstreamError(status_code=None, message="stream broke"),
            502,
            ApiErrorCode.UPSTREAM_UNAVAILABLE,
            "server_error",
            "Upstream provider returned an error",
        ),
        (
            ProviderUpstreamError(status_code=429, message="slow down"),
            429,
            ApiErrorCode.UPSTREAM_RATE_LIMITED,
            "rate_limit_error",
            "Upstream provider rate limit exceeded",
        ),
        (
            ProviderUpstreamError(status_code=500, message="server broke"),
            502,
            ApiErrorCode.UPSTREAM_UNAVAILABLE,
            "server_error",
            "Upstream provider is unavailable",
        ),
        (
            ProviderUpstreamError(status_code=418, message="teapot"),
            400,
            ApiErrorCode.UPSTREAM_REJECTED,
            "invalid_request_error",
            "Upstream provider rejected the request",
        ),
        (
            ProviderError("plain failure"),
            502,
            ApiErrorCode.UPSTREAM_UNAVAILABLE,
            "server_error",
            "Upstream provider is unavailable",
        ),
    ],
)
def test_map_provider_error_translates_each_failure(
    exc: ProviderError,
    expected_status: int,
    expected_code: ApiErrorCode,
    expected_type: str,
    expected_message: str,
) -> None:
    error = map_provider_error(exc)

    assert error.status_code == expected_status
    assert error.code is expected_code
    assert error.error_type == expected_type
    assert error.message == expected_message


def test_upstream_auth_failure_does_not_leak_upstream_details() -> None:
    secret = "sk-upstream-secret-value"
    exc = ProviderUpstreamError(status_code=401, message=f"invalid key {secret}")

    error = map_provider_error(exc)

    assert error.status_code == 502
    assert error.code is ApiErrorCode.UPSTREAM_AUTH_FAILED
    assert error.message == "Upstream provider rejected the gateway credentials"
    assert secret not in error.message
    assert "invalid key" not in error.message


def test_map_provider_error_does_not_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="llm_gateway.services.chat")

    map_provider_error(ProviderTimeoutError())

    records = [record for record in caplog.records if record.name == "llm_gateway.services.chat"]
    assert records == []


async def test_resolve_model_returns_config_and_provider() -> None:
    provider = RecordingProvider()
    service = await make_service(provider)

    resolved = await service.resolve_model(PUBLIC_MODEL)

    assert resolved.config.id == PUBLIC_MODEL
    assert resolved.provider is provider


async def test_resolve_model_unknown_id_returns_model_not_found() -> None:
    service = await make_service(RecordingProvider())

    with pytest.raises(ApiError) as info:
        await service.resolve_model("missing-model")

    assert info.value.status_code == 404
    assert info.value.code is ApiErrorCode.MODEL_NOT_FOUND
    assert info.value.param == "model"
    assert info.value.message == "Model 'missing-model' was not found"


async def test_resolve_model_disabled_returns_model_disabled() -> None:
    service = await make_service(RecordingProvider(), enabled=False)

    with pytest.raises(ApiError) as info:
        await service.resolve_model(PUBLIC_MODEL)

    assert info.value.status_code == 403
    assert info.value.code is ApiErrorCode.MODEL_DISABLED


async def test_resolve_model_with_unconfigured_provider_returns_provider_not_configured() -> None:
    models = InMemoryModelRepository()
    await models.create_model(
        ModelConfig(
            id=PUBLIC_MODEL,
            provider=ProviderName.OPENAI,
            upstream_model=UPSTREAM_MODEL,
            created_at=NOW,
        )
    )
    service = ChatService(models=models, providers=ProviderRegistry({}))

    with pytest.raises(ApiError) as info:
        await service.resolve_model(PUBLIC_MODEL)

    assert info.value.status_code == 503
    assert info.value.code is ApiErrorCode.PROVIDER_NOT_CONFIGURED
    assert info.value.message == "Provider 'openai' is not configured"


async def test_complete_rewrites_public_model_and_forwards_upstream_model() -> None:
    provider = RecordingProvider()
    service = await make_service(provider)

    response = await service.complete(make_request())

    assert provider.upstream_models == [UPSTREAM_MODEL]
    assert response.model == PUBLIC_MODEL


async def test_open_stream_exposes_first_chunk_immediately() -> None:
    provider = RecordingProvider(chunks=[make_chunk("", role="assistant"), make_chunk("hello")])
    service = await make_service(provider)

    stream = await service.open_stream(make_request())

    assert stream.first_chunk.choices[0].delta.role == "assistant"
    assert stream.first_chunk.model == PUBLIC_MODEL
    assert provider.yielded == 1


async def test_open_stream_empty_upstream_returns_invalid_response() -> None:
    service = await make_service(RecordingProvider(chunks=[]))

    with pytest.raises(ApiError) as info:
        await service.open_stream(make_request())

    assert info.value.status_code == 502
    assert info.value.code is ApiErrorCode.UPSTREAM_INVALID_RESPONSE
    assert info.value.message == "Upstream provider returned an empty stream"


async def test_open_stream_first_chunk_timeout_returns_upstream_timeout() -> None:
    service = await make_service(RecordingProvider(stream_error=ProviderTimeoutError()))

    with pytest.raises(ApiError) as info:
        await service.open_stream(make_request())

    assert info.value.status_code == 504
    assert info.value.code is ApiErrorCode.UPSTREAM_TIMEOUT


async def test_chunks_rewrites_model_on_first_and_later_chunks() -> None:
    provider = RecordingProvider(chunks=[make_chunk("one"), make_chunk("two")])
    service = await make_service(provider)
    stream = await service.open_stream(make_request())

    collected = await collect(stream)

    assert [chunk.model for chunk in collected] == [PUBLIC_MODEL, PUBLIC_MODEL]
    assert [chunk.choices[0].delta.content for chunk in collected] == ["one", "two"]


async def test_aclose_closes_upstream_once_and_is_idempotent() -> None:
    provider = RecordingProvider(chunks=[make_chunk("one"), make_chunk("two")])
    service = await make_service(provider)
    stream = await service.open_stream(make_request())

    assert provider.closed == 0
    await stream.aclose()
    assert provider.closed == 1
    await stream.aclose()
    assert provider.closed == 1


async def test_iterating_chunks_after_aclose_does_not_hang() -> None:
    provider = RecordingProvider(chunks=[make_chunk("one"), make_chunk("two")])
    service = await make_service(provider)
    stream = await service.open_stream(make_request())
    await stream.aclose()

    collected = await asyncio.wait_for(collect(stream), timeout=1)

    assert len(collected) == 1
    assert collected[0].model == PUBLIC_MODEL


async def test_open_stream_closes_upstream_and_reraises_unexpected_error() -> None:
    provider = RecordingProvider(stream_error=RuntimeError("provider blew up"))
    service = await make_service(provider)

    with pytest.raises(RuntimeError, match="provider blew up"):
        await service.open_stream(make_request())

    assert provider.closed == 1


async def test_closing_chunks_generator_early_closes_upstream() -> None:
    provider = RecordingProvider(chunks=[make_chunk("one"), make_chunk("two")])
    service = await make_service(provider)
    stream = await service.open_stream(make_request())
    chunks = stream.chunks()

    first = await anext(chunks)
    assert first.model == PUBLIC_MODEL
    assert provider.closed == 0

    await chunks.aclose()

    assert provider.closed == 1


class RuntimeErrorUpstream:
    async def __aiter__(self) -> AsyncGenerator[ChatCompletionChunk, None]:
        yield make_chunk("unused")

    async def aclose(self) -> None:
        raise RuntimeError("aclose(): asynchronous generator is already running")


async def test_aclose_logs_upstream_close_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="llm_gateway.services.chat")
    stream = ChatStream(
        first_chunk=make_chunk("first"),
        model_id=PUBLIC_MODEL,
        upstream=cast(AsyncGenerator[ChatCompletionChunk, None], RuntimeErrorUpstream()),
    )

    await stream.aclose()

    records = [
        record for record in caplog.records if record.getMessage() == "upstream_stream_close_failed"
    ]
    assert len(records) == 1
    attributes = records[0].__dict__
    assert attributes["model_id"] == PUBLIC_MODEL
    assert attributes["error"] == "RuntimeError"
