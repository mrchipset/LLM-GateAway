from __future__ import annotations

import logging
import re

import httpx
import pytest

from llm_gateway.request_context import REQUEST_ID_HEADER

GENERATED_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


async def test_absent_header_generates_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert GENERATED_ID_PATTERN.fullmatch(request_id) is not None


async def test_valid_incoming_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    incoming = "req-abc.123:xyz_ABC"

    response = await client.get("/healthz", headers={REQUEST_ID_HEADER: incoming})

    assert response.headers[REQUEST_ID_HEADER] == incoming


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
