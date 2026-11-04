from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from starlette.types import Message, Receive, Scope, Send

from llm_gateway.app import create_app
from llm_gateway.config import Environment, Settings
from llm_gateway.container import Container
from llm_gateway.lifecycle import InFlightMiddleware, InFlightTracker
from llm_gateway.metrics import (
    build_metrics,
    install_metrics,
    reset_metrics_for_tests,
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


def _counter_total(reader: InMemoryMetricReader, name: str) -> int:
    data = reader.get_metrics_data()
    assert data is not None
    points: list[Any] = []
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name != name:
                    continue
                points.extend(metric.data.data_points)  # pyright: ignore[reportAttributeAccessIssue]
    return sum(int(point.value) for point in points)


async def _empty_receive() -> Message:
    raise AssertionError("receive should not be called")


async def _discard_send(message: Message) -> None:
    del message


def _http_scope() -> Scope:
    return {"type": "http", "method": "GET", "path": "/", "headers": []}


def test_started_and_finished_track_active_requests() -> None:
    tracker = InFlightTracker()

    assert tracker.active == 0
    tracker.started()
    tracker.started()
    assert tracker.active == 2

    tracker.finished()
    assert tracker.active == 1


def test_finished_never_makes_active_negative() -> None:
    tracker = InFlightTracker()

    tracker.finished()
    tracker.finished()

    assert tracker.active == 0


async def test_wait_for_idle_with_zero_timeout_returns_immediately() -> None:
    tracker = InFlightTracker()
    assert await tracker.wait_for_idle(0) is True

    tracker.started()
    assert await tracker.wait_for_idle(0) is False

    tracker.finished()
    assert await tracker.wait_for_idle(0) is True


async def test_waiter_resolves_when_last_request_finishes() -> None:
    tracker = InFlightTracker()
    tracker.started()

    waiter = asyncio.create_task(tracker.wait_for_idle(5.0))
    # Let the waiter reach its first suspension point before finishing the request.
    await asyncio.sleep(0)
    assert waiter.done() is False

    tracker.finished()

    assert await waiter is True
    assert tracker.active == 0


async def test_middleware_holds_request_until_response_body_drains() -> None:
    tracker = InFlightTracker()
    observed: list[int] = []

    async def streaming_app(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"one", "more_body": True})
        observed.append(tracker.active)
        await send({"type": "http.response.body", "body": b"two", "more_body": False})

    middleware = InFlightMiddleware(streaming_app, tracker=tracker)

    await middleware(_http_scope(), _empty_receive, _discard_send)

    assert observed == [1]
    assert tracker.active == 0


async def test_middleware_decrements_when_app_raises() -> None:
    tracker = InFlightTracker()

    async def failing_app(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive, send
        raise RuntimeError("boom")

    middleware = InFlightMiddleware(failing_app, tracker=tracker)

    with pytest.raises(RuntimeError, match="boom"):
        await middleware(_http_scope(), _empty_receive, _discard_send)

    assert tracker.active == 0


def _zero_grace_settings() -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": "test-master-key-0123456789abcdef",
            "shutdown_grace_seconds": 0,
        }
    )


async def test_lifespan_counts_forced_shutdown_when_grace_is_zero(
    make_container: Callable[..., Container],
    metric_reader: InMemoryMetricReader,
) -> None:
    settings = _zero_grace_settings()
    container = make_container(settings)
    container.inflight.started()

    app = create_app(settings=settings, container=container)
    async with app.router.lifespan_context(app):
        assert container.inflight.active == 1

    assert _counter_total(metric_reader, "gateway_forced_shutdowns") == 1
