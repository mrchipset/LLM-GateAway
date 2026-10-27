from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Callable
from typing import Any

from llm_gateway.api.inference import _stream_sse
from llm_gateway.auth.keys import hash_api_key
from llm_gateway.config import Environment, Settings
from llm_gateway.container import Container
from llm_gateway.providers.base import ProviderName, ProviderTimeoutError
from llm_gateway.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatDelta,
)
from llm_gateway.services.audit import AuditService
from llm_gateway.services.chat import ChatStream
from llm_gateway.services.usage import UsageContext, UsageRecorder
from llm_gateway.storage.memory import InMemoryAuditRepository
from llm_gateway.storage.repositories import (
    AuditRequestRecord,
    AuditSessionRecord,
    AuditTurnDiffRecord,
)
from support import (
    CapturingAuditRepository,
    CapturingUsageRepository,
    FailingUsageRepository,
    FrozenClock,
    SlowAuditRepository,
    seed_api_key,
    seed_model,
    seed_tenant,
)
from test_inference_api import (
    EXPECTED_REPLY,
    FAKE_MODEL,
    UPSTREAM_MODEL,
    USER_MESSAGE,
    UsageThenErrorProvider,
    _auth,
    _error,
    _fake_provider,
    _registry,
    _upstream_chunk,
    parse_sse,
)

MASTER_KEY = "test-master-key-0123456789abcdef"


def _settings(*, audit_enabled: bool = True, audit_write_timeout_seconds: float = 2.0) -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": MASTER_KEY,
            "audit_enabled": audit_enabled,
            "audit_write_timeout_seconds": audit_write_timeout_seconds,
        }
    )


async def _setup(
    make_container: Callable[..., Container],
    settings: Settings,
    *,
    audit: Any | None = None,
    provider: Any | None = None,
    tenant_audit: bool = True,
) -> tuple[Container, str, CapturingAuditRepository]:
    capture = audit if audit is not None else CapturingAuditRepository()
    container = make_container(
        settings,
        providers=_registry(provider if provider is not None else _fake_provider()),
        clock=FrozenClock(),
        audit=capture,
    )
    await seed_model(
        container,
        model_id=FAKE_MODEL,
        provider=ProviderName.FAKE,
        upstream_model=UPSTREAM_MODEL,
    )
    tenant = await seed_tenant(container, audit_enabled=tenant_audit)
    secret = await seed_api_key(container, tenant_id=tenant.id)
    return container, secret, capture


def _headers(secret: str, session: str | None = None) -> dict[str, str]:
    headers = _auth(secret)
    if session is not None:
        headers["x-llm-gateway-session-id"] = session
    return headers


class WriteFailingAuditRepository(InMemoryAuditRepository):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    async def record_turn(
        self,
        *,
        session: AuditSessionRecord,
        request: AuditRequestRecord,
        diff: AuditTurnDiffRecord | None,
    ) -> None:
        self.attempts += 1
        raise RuntimeError("audit storage unavailable")


class RuntimeErrorAfterChunkProvider:
    """Yields one content chunk, then breaks with a non-provider error."""

    name = ProviderName.FAKE

    def __init__(self) -> None:
        self.closed = 0

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        raise NotImplementedError

    def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        return self._stream()

    async def _stream(self) -> AsyncGenerator[ChatCompletionChunk, None]:
        try:
            yield _upstream_chunk("partial")
            raise RuntimeError("unexpected stream failure")
        finally:
            self.closed += 1

    async def aclose(self) -> None:
        return None


class ProviderTimeoutProvider:
    """Provider whose calls map to an upstream_timeout ApiError."""

    name = ProviderName.FAKE

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        raise ProviderTimeoutError()

    def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        return self._stream()

    async def _stream(self) -> AsyncGenerator[ChatCompletionChunk, None]:
        raise ProviderTimeoutError()
        yield _upstream_chunk("never")

    async def aclose(self) -> None:
        return None


class MultiChoiceProvider:
    """Streams two choices and keeps their deltas distinct."""

    name = ProviderName.FAKE

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        raise NotImplementedError

    def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        return self._stream()

    async def _stream(self) -> AsyncGenerator[ChatCompletionChunk, None]:
        yield ChatCompletionChunk(
            id="multi-1",
            created=1,
            model="upstream-model",
            choices=[
                ChatCompletionChunkChoice(
                    index=0, delta=ChatDelta(content="zero "), finish_reason=None
                ),
                ChatCompletionChunkChoice(
                    index=1, delta=ChatDelta(content="one "), finish_reason=None
                ),
            ],
        )
        yield ChatCompletionChunk(
            id="multi-2",
            created=1,
            model="upstream-model",
            choices=[
                ChatCompletionChunkChoice(
                    index=0, delta=ChatDelta(content="zero"), finish_reason="stop"
                ),
                ChatCompletionChunkChoice(
                    index=1, delta=ChatDelta(content="one"), finish_reason="length"
                ),
            ],
        )

    async def aclose(self) -> None:
        return None


async def test_non_stream_request_writes_completed_turn(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings()
    container, secret, capture = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE], "temperature": 0.2},
            headers=_headers(secret, "manual-session"),
        )

    assert response.status_code == 200
    assert capture.record_turn_calls == 1
    record = capture.requests[0]
    body = response.json()
    assert record.request_id == response.headers["x-request-id"]
    assert record.request_messages == [{"role": "user", "content": "hello"}]
    assert record.request_params["model"] == FAKE_MODEL
    assert record.request_params["temperature"] == 0.2
    assert "stream" not in record.request_params
    assert record.response_content == EXPECTED_REPLY
    assert record.status == "completed"
    assert record.is_stream is False
    assert record.finish_reason == "stop"
    assert record.prompt_tokens == body["usage"]["prompt_tokens"]
    assert record.completion_tokens == body["usage"]["completion_tokens"]
    assert record.total_tokens == body["usage"]["total_tokens"]
    assert capture.sessions[0].external_session_id == "manual-session"


async def test_streaming_request_accumulates_full_content_and_writes_completed(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings()
    container, secret, capture = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE], "stream": True},
            headers=_headers(secret, "stream-session"),
        )

    assert response.status_code == 200
    frames = parse_sse(response.text)
    assert frames[-1] == "[DONE]"
    assert capture.record_turn_calls == 1
    record = capture.requests[0]
    assert record.is_stream is True
    assert record.response_content == EXPECTED_REPLY
    assert record.status == "completed"
    assert record.finish_reason == "stop"
    assert record.total_tokens is not None


async def test_mid_stream_provider_error_is_recorded_as_upstream_error(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings()
    provider = UsageThenErrorProvider()
    container, secret, capture = await _setup(make_container, settings, provider=provider)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE], "stream": True},
            headers=_headers(secret, "error-session"),
        )

    assert response.status_code == 200
    frames = parse_sse(response.text)
    assert frames[-1] == "[DONE]"
    assert capture.record_turn_calls == 1
    record = capture.requests[0]
    assert record.status == "upstream_error"
    assert record.response_content == "hi"


async def test_stream_close_before_completion_records_client_disconnect_with_partial_content(
    make_container: Callable[..., Container],
) -> None:
    settings = _settings()
    container, secret, capture = await _setup(make_container, settings)
    key = await container.api_keys.get_key_by_hash(hash_api_key(secret))
    assert key is not None
    tenant = await container.tenants.get_tenant(key.tenant_id)
    assert tenant is not None

    service = AuditService(
        settings=container.settings,
        repository=capture,
        tenants=container.tenants,
        clock=FrozenClock(),
    )
    turn = await service.begin(
        tenant_id=tenant.id,
        api_key=key,
        request_id="disconnect-audit",
        model_id=FAKE_MODEL,
        payload=ChatCompletionRequest.model_validate(
            {"model": FAKE_MODEL, "messages": [USER_MESSAGE]}
        ),
        session_header="disconnect-session",
        is_stream=True,
    )
    assert turn is not None

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
        provider=ProviderName.FAKE,
        client_wants_usage=False,
        usage=None,
        upstream=iterator,
    )
    generator = _stream_sse(
        stream,
        recorder=UsageRecorder(repository=CapturingUsageRepository(), clock=FrozenClock()),
        context=UsageContext(
            request_id="disconnect-audit",
            tenant_id=tenant.id,
            api_key_id=key.id,
            model_id=FAKE_MODEL,
            provider=ProviderName.FAKE,
        ),
        audit_turn=turn,
        audit_service=service,
    )

    frame = await anext(generator)
    assert frame.startswith(b"data: ")
    await generator.aclose()

    assert closed == 1
    assert capture.record_turn_calls == 1
    record = capture.requests[0]
    assert record.status == "client_disconnected"
    assert record.response_content == "one"


async def test_audit_write_failure_does_not_change_non_stream_or_stream_responses(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    caplog: Any,
) -> None:
    caplog.set_level(logging.WARNING, logger="llm_gateway.services.audit")
    settings = _settings()
    audit = WriteFailingAuditRepository()
    container, secret, _capture = await _setup(make_container, settings, audit=audit)

    async with make_client(settings, container) as client:
        non_stream = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_headers(secret, "failing-write"),
        )
        stream = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE], "stream": True},
            headers=_headers(secret, "failing-write"),
        )

    assert non_stream.status_code == 200
    assert non_stream.json()["choices"][0]["message"]["content"] == EXPECTED_REPLY
    assert stream.status_code == 200
    assert parse_sse(stream.text)[-1] == "[DONE]"
    assert audit.attempts == 2
    failures = [
        record
        for record in caplog.records
        if record.name == "llm_gateway.services.audit"
        and record.getMessage() == "audit_record_failed"
    ]
    assert len(failures) == 2


async def test_global_audit_disabled_writes_no_rows(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings(audit_enabled=False)
    container, secret, capture = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_headers(secret, "ignored-session"),
        )

    assert response.status_code == 200
    assert capture.record_turn_calls == 0


async def test_invalid_session_header_returns_400_envelope_before_inference(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings()
    container, secret, capture = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_headers(secret, "not valid!"),
        )

    assert response.status_code == 400
    error = _error(response)
    assert error["code"] == "invalid_session_id"
    assert error["param"] == "x-llm-gateway-session-id"
    assert response.headers["x-request-id"]
    assert capture.record_turn_calls == 0


async def test_usage_failure_still_records_audit(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings()
    capture = CapturingAuditRepository()
    container = make_container(
        settings,
        providers=_registry(_fake_provider()),
        clock=FrozenClock(),
        usage=FailingUsageRepository(),
        audit=capture,
    )
    await seed_model(
        container,
        model_id=FAKE_MODEL,
        provider=ProviderName.FAKE,
        upstream_model=UPSTREAM_MODEL,
    )
    tenant = await seed_tenant(container, audit_enabled=True)
    secret = await seed_api_key(container, tenant_id=tenant.id)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_headers(secret, "usage-failure"),
        )

    assert response.status_code == 200
    assert capture.record_turn_calls == 1
    assert capture.requests[0].status == "completed"


async def test_mid_stream_provider_error_keeps_usage_recording(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings()
    provider = UsageThenErrorProvider()
    container, secret, capture = await _setup(make_container, settings, provider=provider)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE], "stream": True},
            headers=_headers(secret, "error-frames"),
        )

    frames = parse_sse(response.text)
    assert json.loads(frames[1])["error"]["code"] == "upstream_rejected"
    assert capture.record_turn_calls == 1


async def test_mid_stream_non_provider_error_is_recorded_as_upstream_error(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings()
    provider = RuntimeErrorAfterChunkProvider()
    container, secret, capture = await _setup(make_container, settings, provider=provider)

    async with make_client(settings, container) as client:
        await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE], "stream": True},
            headers=_headers(secret, "runtime-error"),
        )

    assert capture.record_turn_calls == 1
    record = capture.requests[0]
    assert record.status == "upstream_error"
    assert record.response_content == "partial"
    assert provider.closed == 1


async def test_stream_audit_records_only_the_first_choice(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings()
    container, secret, capture = await _setup(
        make_container, settings, provider=MultiChoiceProvider()
    )

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE], "stream": True, "n": 2},
            headers=_headers(secret, "multi-choice"),
        )

    assert response.status_code == 200
    chunk = json.loads(parse_sse(response.text)[0])
    assert [choice["index"] for choice in chunk["choices"]] == [0, 1]
    assert capture.record_turn_calls == 1
    record = capture.requests[0]
    assert record.response_content == "zero zero"
    assert record.finish_reason == "stop"


async def test_non_stream_api_error_is_recorded_as_client_error(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings()
    container, secret, capture = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "missing-model", "messages": [USER_MESSAGE]},
            headers=_headers(secret, "client-error"),
        )

    assert response.status_code == 404
    assert _error(response)["code"] == "model_not_found"
    assert capture.record_turn_calls == 1
    assert capture.requests[0].status == "client_error"


async def test_audit_disabled_skips_invalid_session_header_validation(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings(audit_enabled=False)
    container, secret, capture = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_headers(secret, "not valid!"),
        )

    assert response.status_code == 200
    assert capture.record_turn_calls == 0


async def test_audit_write_timeout_does_not_affect_non_stream_response(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    caplog: Any,
) -> None:
    caplog.set_level(logging.WARNING, logger="llm_gateway.services.audit")
    settings = _settings(audit_write_timeout_seconds=0.01)
    audit = SlowAuditRepository()
    container, secret, capture = await _setup(make_container, settings, audit=audit)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_headers(secret, "slow-audit"),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == EXPECTED_REPLY
    assert body["usage"]["total_tokens"] > 0
    assert capture.record_turn_calls == 0

    failures = [
        record
        for record in caplog.records
        if record.name == "llm_gateway.services.audit"
        and record.getMessage() == "audit_record_failed"
    ]
    assert len(failures) == 1
    assert failures[0].__dict__["error"] == "TimeoutError"
    assert "hello" not in caplog.text
    assert EXPECTED_REPLY not in caplog.text


async def test_audit_write_timeout_does_not_affect_stream_response(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    caplog: Any,
) -> None:
    caplog.set_level(logging.WARNING, logger="llm_gateway.services.audit")
    settings = _settings(audit_write_timeout_seconds=0.01)
    audit = SlowAuditRepository()
    container, secret, capture = await _setup(make_container, settings, audit=audit)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE], "stream": True},
            headers=_headers(secret, "slow-audit-stream"),
        )

    assert response.status_code == 200
    frames = parse_sse(response.text)
    assert frames[-1] == "[DONE]"
    reply = "".join(
        json.loads(frame)["choices"][0]["delta"].get("content") or ""
        for frame in frames[:-1]
        if json.loads(frame)["choices"]
    )
    assert reply == EXPECTED_REPLY
    assert capture.record_turn_calls == 0

    failures = [
        record
        for record in caplog.records
        if record.name == "llm_gateway.services.audit"
        and record.getMessage() == "audit_record_failed"
    ]
    assert len(failures) == 1
    assert failures[0].__dict__["error"] == "TimeoutError"
    assert "hello" not in caplog.text
    assert EXPECTED_REPLY not in caplog.text


async def test_non_stream_upstream_timeout_is_recorded_as_upstream_error(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings()
    container, secret, capture = await _setup(
        make_container, settings, provider=ProviderTimeoutProvider()
    )

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_headers(secret, "timeout-audit"),
        )

    assert response.status_code == 504
    assert _error(response)["code"] == "upstream_timeout"
    assert capture.record_turn_calls == 1
    assert capture.requests[0].status == "upstream_error"


async def test_stream_open_failure_with_model_not_found_is_recorded_as_client_error(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
) -> None:
    settings = _settings()
    container, secret, capture = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "missing-model", "messages": [USER_MESSAGE], "stream": True},
            headers=_headers(secret, "stream-client-error"),
        )

    assert response.status_code == 404
    assert _error(response)["code"] == "model_not_found"
    assert capture.record_turn_calls == 1
    record = capture.requests[0]
    assert record.status == "client_error"
    assert record.is_stream is True
