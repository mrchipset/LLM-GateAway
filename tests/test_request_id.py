from __future__ import annotations

import logging
import re

import httpx
import pytest
from starlette.types import Message, Receive, Scope, Send

from llm_gateway.request_context import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
)

GENERATED_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


async def test_absent_header_generates_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert GENERATED_ID_PATTERN.fullmatch(request_id) is not None


async def test_valid_incoming_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    incoming = "req-abc.123:xyz_ABC"

    response = await client.get("/healthz", headers={REQUEST_ID_HEADER: incoming})

    assert response.headers[REQUEST_ID_HEADER] == incoming


async def test_request_id_of_max_length_is_echoed(client: httpx.AsyncClient) -> None:
    incoming = "a" * 64

    response = await client.get("/healthz", headers={REQUEST_ID_HEADER: incoming})

    assert response.headers[REQUEST_ID_HEADER] == incoming


async def test_request_id_over_max_length_is_replaced(client: httpx.AsyncClient) -> None:
    incoming = "a" * 65

    response = await client.get("/healthz", headers={REQUEST_ID_HEADER: incoming})

    request_id = response.headers[REQUEST_ID_HEADER]
    assert request_id != incoming
    assert GENERATED_ID_PATTERN.fullmatch(request_id) is not None


@pytest.mark.parametrize("incoming", ["a" * 300, "contains spaces"])
async def test_invalid_incoming_request_id_is_replaced(
    client: httpx.AsyncClient,
    incoming: str,
) -> None:
    response = await client.get("/healthz", headers={REQUEST_ID_HEADER: incoming})

    request_id = response.headers[REQUEST_ID_HEADER]
    assert request_id != incoming
    assert GENERATED_ID_PATTERN.fullmatch(request_id) is not None


async def test_access_log_records_request_metadata(
    client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="llm_gateway.access")

    response = await client.get(
        "/healthz",
        headers={REQUEST_ID_HEADER: "req-log-1"},
    )

    records = [record for record in caplog.records if record.name == "llm_gateway.access"]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "request_id", None) == "req-log-1"
    assert getattr(record, "status_code", None) == response.status_code
    duration_ms = getattr(record, "duration_ms", None)
    assert isinstance(duration_ms, float)
    assert duration_ms >= 0
    assert getattr(record, "method", None) == "GET"
    assert getattr(record, "path", None) == "/healthz"
    assert getattr(record, "client_disconnected", None) is False


async def test_access_log_records_client_disconnect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="llm_gateway.access")

    sent_messages: list[Message] = []

    async def inner_app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        message = await receive()
        assert message["type"] == "http.disconnect"

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent_messages.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/stream",
        "raw_path": b"/stream",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }

    middleware = RequestContextMiddleware(inner_app)
    await middleware(scope, receive, send)

    records = [record for record in caplog.records if record.name == "llm_gateway.access"]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "client_disconnected", None) is True
    assert getattr(record, "status_code", None) == 200
    assert sent_messages[0]["type"] == "http.response.start"
