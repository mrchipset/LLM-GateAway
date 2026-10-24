from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from typing import Any, Literal

import httpx
import pytest

from llm_gateway.api.inference import _stream_sse
from llm_gateway.config import Environment, Settings, StorageBackend
from llm_gateway.container import Container, build_container
from llm_gateway.providers.base import (
    ChatProvider,
    ProviderError,
    ProviderName,
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatDelta,
)
from llm_gateway.services.chat import ChatStream
from support import FrozenClock, seed_api_key, seed_model

FAKE_MODEL = "fake-model"
UPSTREAM_MODEL = "upstream-fake-model"
USER_MESSAGE = {"role": "user", "content": "hello"}
EXPECTED_REPLY = "fake completion for: hello"

Role = Literal["system", "developer", "user", "assistant", "tool"]


def _fake_provider() -> FakeProvider:
    return FakeProvider(clock=FrozenClock())


def _registry(provider: ChatProvider) -> ProviderRegistry:
    return ProviderRegistry({provider.name: provider})


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _error(response: httpx.Response) -> dict[str, object]:
    body = response.json()
    error = body["error"]
    assert isinstance(error, dict)
    return error


def parse_sse(body: str) -> list[str]:
    frames = [frame for frame in body.split("\n\n") if frame]
    assert all(frame.startswith("data: ") for frame in frames), frames
    return [frame[len("data: ") :] for frame in frames]


async def _fake_setup(
    make_container: Callable[..., Container],
    settings: Settings,
    *,
    model_id: str = FAKE_MODEL,
    enabled: bool = True,
) -> tuple[Container, str]:
    provider = _fake_provider()
    container = make_container(
        settings,
        providers=_registry(provider),
        clock=FrozenClock(),
    )
    await seed_model(
        container,
        model_id=model_id,
        provider=ProviderName.FAKE,
        upstream_model=UPSTREAM_MODEL,
        enabled=enabled,
    )
    secret = await seed_api_key(container)
    return container, secret


def _upstream_chunk(content: str, *, role: Role | None = None) -> ChatCompletionChunk:
    delta = ChatDelta(role=role, content=content)
    return ChatCompletionChunk(
        id="upstream-chunk",
        created=1,
        model="upstream-model",
        choices=[ChatCompletionChunkChoice(index=0, delta=delta)],
    )


class FailingProvider:
    """Provider that fails before the first chunk or after one chunk."""

    name = ProviderName.OPENAI

    def __init__(self, *, error: ProviderError, fail_after_chunk: bool = False) -> None:
        self._error = error
        self._fail_after_chunk = fail_after_chunk
        self.closed = 0

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        raise self._error

    def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        return self._stream()

    async def _stream(self) -> AsyncGenerator[ChatCompletionChunk, None]:
        try:
            if self._fail_after_chunk:
                yield _upstream_chunk("hi", role="assistant")
            raise self._error
        finally:
            self.closed += 1

    async def aclose(self) -> None:
        return None


async def _error_setup(
    make_container: Callable[..., Container],
    settings: Settings,
    provider: FailingProvider,
) -> tuple[Container, str]:
    container = make_container(
        settings,
        providers=_registry(provider),
        clock=FrozenClock(),
    )
    await seed_model(
        container,
        model_id="broken-model",
        provider=ProviderName.OPENAI,
        upstream_model="upstream-broken",
    )
    secret = await seed_api_key(container)
    return container, secret


async def test_non_stream_completion_returns_public_model_and_usage(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container, secret = await _fake_setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_auth(secret),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == FAKE_MODEL
    assert body["choices"][0]["message"]["content"] == EXPECTED_REPLY
    assert body["usage"]["total_tokens"] > 0
    assert response.headers["x-request-id"]


async def test_stream_emits_sse_chunks_for_the_same_reply_as_non_stream(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container, secret = await _fake_setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE], "stream": True},
            headers=_auth(secret),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = parse_sse(response.text)
    assert frames[-1] == "[DONE]"

    chunks = [json.loads(frame) for frame in frames[:-1]]
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    for chunk in chunks:
        assert chunk["model"] == FAKE_MODEL

    reply = "".join(
        chunk["choices"][0]["delta"].get("content") or "" for chunk in chunks if chunk["choices"]
    )
    assert reply == EXPECTED_REPLY


async def test_stream_with_usage_option_emits_usage_before_done(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container, secret = await _fake_setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": FAKE_MODEL,
                "messages": [USER_MESSAGE],
                "stream": True,
                "stream_options": {"include_usage": True},
            },
            headers=_auth(secret),
        )

    frames = parse_sse(response.text)
    assert frames[-1] == "[DONE]"

    usage_chunk = json.loads(frames[-2])
    assert usage_chunk["usage"] is not None
    assert usage_chunk["usage"]["total_tokens"] > 0
    assert usage_chunk["choices"] == []


async def test_unknown_model_returns_model_not_found(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container, secret = await _fake_setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "missing-model", "messages": [USER_MESSAGE]},
            headers=_auth(secret),
        )

    assert response.status_code == 404
    error = _error(response)
    assert error["code"] == "model_not_found"
    assert error["param"] == "model"


async def test_disabled_model_returns_model_disabled(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container, secret = await _fake_setup(make_container, settings, enabled=False)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_auth(secret),
        )

    assert response.status_code == 403
    assert _error(response)["code"] == "model_disabled"


async def test_model_with_unconfigured_provider_returns_provider_not_configured(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(
        settings,
        providers=_registry(_fake_provider()),
        clock=FrozenClock(),
    )
    await seed_model(
        container,
        model_id="openai-model",
        provider=ProviderName.OPENAI,
        upstream_model="gpt-upstream",
    )
    secret = await seed_api_key(container)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "openai-model", "messages": [USER_MESSAGE]},
            headers=_auth(secret),
        )

    assert response.status_code == 503
    assert _error(response)["code"] == "provider_not_configured"


async def test_missing_authorization_returns_missing_api_key(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container, _ = await _fake_setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
        )

    assert response.status_code == 401
    assert _error(response)["code"] == "missing_api_key"


async def test_master_key_is_rejected_on_inference_routes(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container, _ = await _fake_setup(make_container, settings)
    master_key = settings.master_key.get_secret_value()

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_auth(master_key),
        )

    assert response.status_code == 401
    assert _error(response)["code"] == "master_key_not_allowed"


@pytest.mark.parametrize(
    "payload",
    [
        {"model": FAKE_MODEL, "messages": []},
        {"messages": [USER_MESSAGE]},
    ],
)
async def test_invalid_request_body_returns_400(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
    payload: dict[str, object],
) -> None:
    container, secret = await _fake_setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json=payload,
            headers=_auth(secret),
        )

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_request_body"


async def test_first_chunk_timeout_returns_json_504(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    provider = FailingProvider(error=ProviderTimeoutError())
    container, secret = await _error_setup(make_container, settings, provider)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "broken-model", "messages": [USER_MESSAGE], "stream": True},
            headers=_auth(secret),
        )

    assert response.status_code == 504
    assert response.headers["content-type"].startswith("application/json")
    assert "data:" not in response.text
    assert _error(response)["code"] == "upstream_timeout"


async def test_first_chunk_upstream_401_returns_upstream_auth_failed(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    provider = FailingProvider(
        error=ProviderUpstreamError(status_code=401, message="bad upstream key")
    )
    container, secret = await _error_setup(make_container, settings, provider)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "broken-model", "messages": [USER_MESSAGE], "stream": True},
            headers=_auth(secret),
        )

    assert response.status_code == 502
    error = _error(response)
    assert error["code"] == "upstream_auth_failed"
    assert "bad upstream key" not in response.text


async def test_mid_stream_error_returns_sse_error_frame_and_closes_upstream(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    provider = FailingProvider(
        error=ProviderUpstreamError(status_code=400, message="upstream rejected"),
        fail_after_chunk=True,
    )
    container, secret = await _error_setup(make_container, settings, provider)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "broken-model", "messages": [USER_MESSAGE], "stream": True},
            headers=_auth(secret),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = parse_sse(response.text)
    assert frames[-1] == "[DONE]"

    first = json.loads(frames[0])
    assert first["choices"][0]["delta"]["content"] == "hi"

    error_frame = json.loads(frames[1])
    assert error_frame["error"]["code"] == "upstream_rejected"
    assert error_frame["error"]["message"] == "upstream rejected"
    assert provider.closed == 1


async def test_models_lists_only_enabled_models(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(
        settings,
        providers=_registry(_fake_provider()),
        clock=FrozenClock(),
    )
    await seed_model(container, model_id="enabled-model", provider=ProviderName.FAKE)
    await seed_model(
        container,
        model_id="disabled-model",
        provider=ProviderName.FAKE,
        enabled=False,
    )
    secret = await seed_api_key(container)

    async with make_client(settings, container) as client:
        response = await client.get("/v1/models", headers=_auth(secret))

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert [model["id"] for model in body["data"]] == ["enabled-model"]
    model = body["data"][0]
    assert model["owned_by"] == "fake"
    assert isinstance(model["created"], int)


async def test_models_requires_api_key(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container, _ = await _fake_setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.get("/v1/models")

    assert response.status_code == 401
    assert _error(response)["code"] == "missing_api_key"


async def test_stream_sse_aclose_releases_upstream_exactly_once() -> None:
    closed = 0

    async def upstream() -> AsyncGenerator[ChatCompletionChunk, None]:
        nonlocal closed
        try:
            yield _upstream_chunk("one")
            yield _upstream_chunk("two")
        finally:
            closed += 1

    iterator = upstream()
    first_chunk = await anext(iterator)
    stream = ChatStream(
        first_chunk=first_chunk,
        model_id=FAKE_MODEL,
        upstream=iterator,
    )
    generator = _stream_sse(stream)

    frame = await anext(generator)
    assert frame.startswith(b"data: ")
    assert closed == 0

    await generator.aclose()

    assert closed == 1


def test_build_container_rejects_postgres_backend() -> None:
    postgres_settings = Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": "test-master-key-0123456789abcdef",
            "storage_backend": StorageBackend.POSTGRES,
            "database_url": "postgresql+asyncpg://user:pass@localhost/db",
        }
    )

    with pytest.raises(RuntimeError, match="postgres storage backend is not wired yet"):
        build_container(postgres_settings)
