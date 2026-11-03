from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from llm_gateway.config import Environment, Settings
from llm_gateway.container import Container
from llm_gateway.metrics import (
    build_metrics,
    configure_metrics,
    install_metrics,
    reset_metrics_for_tests,
    shutdown_metrics,
)
from llm_gateway.providers.base import ProviderName
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.providers.openai import OpenAIProvider
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.providers.retry import RetryPolicy
from llm_gateway.schemas.chat import ChatCompletionRequest
from support import (
    FailingUsageRepository,
    FrozenClock,
    seed_api_key,
    seed_model,
    seed_tenant,
)

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


@pytest.fixture(name="metric_reader")
def metric_reader_fixture() -> Iterator[InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    install_metrics(build_metrics(provider.get_meter("test")))
    try:
        yield reader
    finally:
        reset_metrics_for_tests()
        provider.shutdown()


def metric_points(reader: InMemoryMetricReader, name: str) -> list[Any]:
    data = reader.get_metrics_data()
    assert data is not None
    points: list[Any] = []
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == name:
                    points.extend(metric.data.data_points)  # pyright: ignore[reportAttributeAccessIssue]
    return points


def counter_total(reader: InMemoryMetricReader, name: str, **labels: str) -> int:
    total = 0
    for point in metric_points(reader, name):
        attributes = dict(point.attributes)
        if all(attributes.get(key) == value for key, value in labels.items()):
            total += int(point.value)
    return total


def histogram_count(reader: InMemoryMetricReader, name: str, **labels: str) -> int:
    count = 0
    for point in metric_points(reader, name):
        attributes = dict(point.attributes)
        if all(attributes.get(key) == value for key, value in labels.items()):
            count += int(point.count)
    return count


def make_provider(
    handler: Callable[[httpx.Request], httpx.Response],
) -> OpenAIProvider:
    return OpenAIProvider(
        api_key="sk-upstream-test",
        base_url="https://upstream.test/v1",
        timeout=httpx.Timeout(5.0),
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.001),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            timeout=httpx.Timeout(5.0),
        ),
        sleeper=_no_sleep,
    )


async def _no_sleep(_: float) -> None:
    return None


def _request() -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(
        {"model": "public-model", "messages": [{"role": "user", "content": "hi"}]}
    )


def test_repeated_configuration_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    shutdowns: list[str] = []

    class FakeServer:
        def shutdown(self) -> None:
            shutdowns.append("server")

    class FakeThread:
        def join(self, timeout: float | None = None) -> None:
            del timeout

    monkeypatch.setattr(
        "llm_gateway.metrics._start_metrics_server",
        lambda host, port: (FakeServer(), FakeThread()),
    )
    configured = Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": "test-master-key-0123456789abcdef",
            "metrics_enabled": True,
            "metrics_host": "127.0.0.1",
            "metrics_port": 19999,
        }
    )
    try:
        first = configure_metrics(configured)
        second = configure_metrics(configured)
    finally:
        shutdown_metrics()
        reset_metrics_for_tests()

    assert first is second
    assert shutdowns == ["server"]


async def test_http_metrics_use_the_route_template_not_the_concrete_path(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    metric_reader: InMemoryMetricReader,
) -> None:
    container = make_container(settings)
    key_id = uuid4()
    master = settings.master_key.get_secret_value()

    async with make_client(settings, container) as client:
        response = await client.delete(
            f"/api/v1/keys/{key_id}",
            headers={"Authorization": f"Bearer {master}"},
        )

    assert response.status_code == 404
    assert (
        counter_total(
            metric_reader,
            "gateway_requests",
            route="/keys/{key_id}",
            method="DELETE",
            status_code="404",
        )
        == 1
    )
    assert (
        histogram_count(
            metric_reader,
            "gateway_request_duration_seconds",
            route="/keys/{key_id}",
        )
        == 1
    )
    for point in metric_points(metric_reader, "gateway_requests"):
        assert str(key_id) not in str(dict(point.attributes))


async def test_upstream_metrics_count_each_attempt_separately(
    metric_reader: InMemoryMetricReader,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(500, json={"error": {"message": "boom"}})
        return httpx.Response(200, json=COMPLETION_BODY)

    provider = make_provider(handler)

    with trace.get_tracer("test").start_as_current_span("root"):
        await provider.complete(upstream_model="upstream", request=_request())

    assert len(seen) == 2
    for status in ("500", "200"):
        assert (
            counter_total(
                metric_reader,
                "gateway_upstream_requests",
                provider="openai",
                model="public-model",
                status=status,
            )
            == 1
        )
    assert (
        histogram_count(
            metric_reader,
            "gateway_upstream_duration_seconds",
            provider="openai",
            model="public-model",
        )
        == 2
    )


async def test_streaming_records_time_to_first_token(
    metric_reader: InMemoryMetricReader,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=STREAM_BODY,
            headers={"content-type": "text/event-stream"},
        )

    provider = make_provider(handler)

    with trace.get_tracer("test").start_as_current_span("root"):
        chunks = [
            chunk async for chunk in provider.stream(upstream_model="upstream", request=_request())
        ]

    assert chunks[0].choices[0].delta.content == "hi"
    assert (
        histogram_count(
            metric_reader,
            "gateway_upstream_ttft_seconds",
            provider="openai",
            model="public-model",
        )
        == 1
    )
    assert (
        counter_total(
            metric_reader,
            "gateway_upstream_requests",
            provider="openai",
            model="public-model",
            status="ok",
        )
        == 1
    )


async def _fake_stack(
    settings: Settings,
    make_container: Callable[..., Container],
    *,
    requests_per_minute: int | None = None,
    usage: Any = None,
) -> tuple[Container, str]:
    clock = FrozenClock(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
    provider = FakeProvider(clock=clock)
    container = make_container(
        settings,
        clock=clock,
        providers=ProviderRegistry({ProviderName.FAKE: provider}),
        usage=usage,
    )
    await seed_model(container, model_id="fake-model")
    tenant = await seed_tenant(
        container,
        name="metrics-tenant",
        requests_per_minute=requests_per_minute,
    )
    secret = await seed_api_key(container, tenant_id=tenant.id)
    return container, secret


async def _call_models(client: httpx.AsyncClient, secret: str) -> httpx.Response:
    return await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {secret}"},
        json={"model": "fake-model", "messages": [{"role": "user", "content": "hi"}]},
    )


async def test_rate_limit_rejection_is_counted(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    metric_reader: InMemoryMetricReader,
) -> None:
    container, secret = await _fake_stack(
        settings,
        make_container,
        requests_per_minute=1,
    )

    async with make_client(settings, container) as client:
        first = await _call_models(client, secret)
        second = await _call_models(client, secret)

    assert first.status_code == 200
    assert second.status_code == 429
    assert counter_total(metric_reader, "gateway_rejections", reason="rate_limit") == 1


async def test_usage_write_failure_is_counted(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    metric_reader: InMemoryMetricReader,
) -> None:
    container, secret = await _fake_stack(
        settings,
        make_container,
        usage=FailingUsageRepository(),
    )

    async with make_client(settings, container) as client:
        response = await _call_models(client, secret)

    assert response.status_code == 200
    assert (
        counter_total(
            metric_reader,
            "gateway_usage_write_failures",
            reason="write_failed",
        )
        == 1
    )
