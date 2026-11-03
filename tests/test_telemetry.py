from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import Tracer
from pydantic import ValidationError

from llm_gateway.config import Environment, Settings
from llm_gateway.container import Container
from llm_gateway.logging import JsonFormatter
from llm_gateway.providers.base import ProviderName
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.providers.openai import OpenAIProvider
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.providers.retry import RetryPolicy
from llm_gateway.schemas.chat import ChatCompletionRequest
from llm_gateway.telemetry import Telemetry, configure_telemetry, current_trace_ids
from support import CapturingUsageRepository, FrozenClock, seed_api_key, seed_model

INBOUND_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
INBOUND_PARENT = "00f067aa0ba902b7"
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")

COMPLETION_BODY: dict[str, object] = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "upstream",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hello"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
}

STREAM_BODY = (
    'data: {"id":"c1","object":"chat.completion.chunk","created":1,"model":"m",'
    '"choices":[{"index":0,"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
    "data: [DONE]\n\n"
)


def make_telemetry() -> tuple[Telemetry, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=ALWAYS_ON)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return Telemetry(tracer=provider.get_tracer("test"), provider=provider), exporter


def parse_traceparent(value: str) -> tuple[str, str, str]:
    match = _TRACEPARENT.fullmatch(value)
    assert match is not None, f"malformed traceparent: {value!r}"
    return match.group(1), match.group(2), match.group(3)


def trace_hex(span: ReadableSpan) -> str:
    context = span.context
    assert context is not None
    return format(context.trace_id, "032x")


def parent_span_hex(span: ReadableSpan) -> str | None:
    parent = span.parent
    if parent is None:
        return None
    return format(parent.span_id, "016x")


def span_attr(span: ReadableSpan, key: str) -> object:
    attributes = span.attributes
    assert attributes is not None, f"span {span.name!r} has no attributes"
    assert key in attributes, f"span {span.name!r} is missing {key!r}"
    return attributes[key]


async def _no_sleep(_: float) -> None:
    return None


def make_provider(tracer: Tracer | None, handler: Callable[[httpx.Request], httpx.Response]):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(5.0),
    )
    return OpenAIProvider(
        api_key="sk-upstream-test",
        base_url="https://upstream.test/v1",
        timeout=httpx.Timeout(5.0),
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.001),
        client=client,
        sleeper=_no_sleep,
        tracer=tracer,
    )


def _request() -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(
        {"model": "public-model", "messages": [{"role": "user", "content": "hi"}]}
    )


def test_disabled_tracing_installs_no_provider(settings: Settings) -> None:
    telemetry = configure_telemetry(settings)

    assert telemetry.enabled is False
    assert telemetry.provider is None


def test_enabling_tracing_without_endpoint_fails_at_startup() -> None:
    with pytest.raises(ValidationError, match="tracing_endpoint is required"):
        Settings(
            **{
                "_env_file": None,
                "environment": Environment.TEST,
                "master_key": "test-master-key-0123456789abcdef",
                "tracing_enabled": True,
            }
        )


async def test_server_span_reuses_inbound_traceparent(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    telemetry, exporter = make_telemetry()
    container = make_container(settings, telemetry=telemetry)

    async with make_client(settings, container) as client:
        response = await client.get(
            "/healthz",
            headers={"traceparent": f"00-{INBOUND_TRACE}-{INBOUND_PARENT}-01"},
        )

    assert response.status_code == 200
    spans = [span for span in exporter.get_finished_spans() if span.name == "http.server"]
    assert len(spans) == 1
    span = spans[0]
    assert trace_hex(span) == INBOUND_TRACE
    assert parent_span_hex(span) == INBOUND_PARENT
    assert span_attr(span, "http.response.status_code") == 200


async def test_invalid_traceparent_starts_a_new_trace(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    telemetry, exporter = make_telemetry()
    container = make_container(settings, telemetry=telemetry)
    all_zero = f"00-{'0' * 32}-{'0' * 16}-01"

    async with make_client(settings, container) as client:
        response = await client.get("/healthz", headers={"traceparent": all_zero})

    assert response.status_code == 200
    span = next(span for span in exporter.get_finished_spans() if span.name == "http.server")
    assert span.parent is None
    assert trace_hex(span) != "0" * 32


async def test_disabled_tracing_sends_no_traceparent_upstream() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=COMPLETION_BODY)

    provider = make_provider(_disabled_tracer(), handler)

    await provider.complete(upstream_model="upstream", request=_request())

    assert len(seen) == 1
    assert "traceparent" not in seen[0].headers


def _disabled_tracer() -> Tracer:
    return trace.get_tracer("test.disabled")


async def test_each_retry_attempt_gets_its_own_parent_but_the_same_trace() -> None:
    telemetry, exporter = make_telemetry()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(500, json={"error": {"message": "upstream exploded"}})
        return httpx.Response(200, json=COMPLETION_BODY)

    provider = make_provider(telemetry.tracer, handler)

    with telemetry.tracer.start_as_current_span("root") as root:
        result = await provider.complete(upstream_model="upstream", request=_request())
        root_trace_id = format(root.get_span_context().trace_id, "032x")

    assert result.choices[0].message.content == "hello"
    assert len(seen) == 2

    first = parse_traceparent(seen[0].headers["traceparent"])
    second = parse_traceparent(seen[1].headers["traceparent"])
    assert first[0] == second[0] == root_trace_id
    assert first[1] != second[1]
    assert int(first[2], 16) & 0x01 == 1
    assert int(second[2], 16) & 0x01 == 1

    attempt_spans = sorted(
        (span for span in exporter.get_finished_spans() if span.name == "openai chat"),
        key=lambda span: cast(int, span_attr(span, "llm.attempt")),
    )
    assert [span_attr(span, "llm.attempt") for span in attempt_spans] == [1, 2]
    assert span_attr(attempt_spans[0], "http.response.status_code") == 500
    assert span_attr(attempt_spans[1], "http.response.status_code") == 200
    assert {trace_hex(span) for span in attempt_spans} == {root_trace_id}


async def test_streaming_span_records_time_to_first_token() -> None:
    telemetry, exporter = make_telemetry()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=STREAM_BODY,
            headers={"content-type": "text/event-stream"},
        )

    provider = make_provider(telemetry.tracer, handler)

    with telemetry.tracer.start_as_current_span("root"):
        chunks = [
            chunk async for chunk in provider.stream(upstream_model="upstream", request=_request())
        ]

    assert chunks[0].choices[0].delta.content == "hi"
    span = next(span for span in exporter.get_finished_spans() if span.name == "openai chat")
    assert span_attr(span, "llm.stream") is True
    assert cast(float, span_attr(span, "llm.ttft_ms")) >= 0
    assert span_attr(span, "llm.stream_completed") is True


def test_json_logs_carry_trace_and_span_ids_only_inside_a_span() -> None:
    telemetry, _ = make_telemetry()
    formatter = JsonFormatter()
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", None, None)

    with telemetry.tracer.start_as_current_span("root"):
        expected_trace, expected_span = current_trace_ids()
        payload = json.loads(formatter.format(record))

    assert payload["trace_id"] == expected_trace
    assert payload["span_id"] == expected_span
    assert "trace_id" not in json.loads(formatter.format(record))


async def test_usage_record_carries_the_server_trace_id(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    telemetry, exporter = make_telemetry()
    usage = CapturingUsageRepository()
    provider = FakeProvider(clock=FrozenClock(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)))
    container = make_container(
        settings,
        providers=ProviderRegistry({ProviderName.FAKE: provider}),
        usage=usage,
        telemetry=telemetry,
    )
    await seed_model(container, model_id="fake-model")
    secret = await seed_api_key(container)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {secret}"},
            json={"model": "fake-model", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200
    server_span = next(span for span in exporter.get_finished_spans() if span.name == "http.server")
    expected_trace_id = trace_hex(server_span)
    assert len(usage.records) == 1
    assert usage.records[0].trace_id == expected_trace_id
    assert server_span.attributes is not None
    assert server_span.attributes["llm.model_id"] == "fake-model"
