from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import cast
from uuid import UUID

import pytest

from llm_gateway.logging import JsonFormatter, configure_logging
from llm_gateway.request_context import request_id_scope

TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class _Color(Enum):
    RED = "red"


def _make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.__dict__.update(extra)
    return record


def _render(**extra: object) -> dict[str, object]:
    formatted = JsonFormatter().format(_make_record(**extra))
    return cast(dict[str, object], json.loads(formatted))


def test_formatter_emits_one_json_line_with_core_fields() -> None:
    payload = _render()

    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "hello world"
    ts = payload["ts"]
    assert isinstance(ts, str)
    assert TS_PATTERN.fullmatch(ts) is not None


def test_sensitive_keys_are_redacted_recursively() -> None:
    payload = _render(
        authorization="Bearer secret",
        openai_api_key="sk-test-value",
        nested={"api_key": "abc", "messages": [{"content": "private prompt"}]},
        items=[{"token": "nested-token"}],
    )

    assert payload["authorization"] == "[redacted]"
    assert payload["openai_api_key"] == "[redacted]"
    nested = payload["nested"]
    assert isinstance(nested, dict)
    assert nested["api_key"] == "[redacted]"
    assert nested["messages"] == "[redacted]"
    items = payload["items"]
    assert isinstance(items, list)
    first = items[0]
    assert isinstance(first, dict)
    assert first["token"] == "[redacted]"


def test_json_default_serializes_supported_value_types() -> None:
    payload = _render(
        when=datetime(2026, 1, 1, tzinfo=UTC),
        ident=UUID("12345678-1234-5678-1234-567812345678"),
        amount=Decimal("1.25"),
        color=_Color.RED,
    )

    assert payload["when"] == "2026-01-01T00:00:00+00:00"
    assert payload["ident"] == "12345678-1234-5678-1234-567812345678"
    assert payload["amount"] == "1.25"
    assert payload["color"] == "red"


def test_unknown_extra_value_type_raises_type_error() -> None:
    record = _make_record(opaque=object())

    with pytest.raises(TypeError):
        JsonFormatter().format(record)


def test_request_id_is_included_when_bound() -> None:
    with request_id_scope("req-ctx-1"):
        payload = _render()

    assert payload["request_id"] == "req-ctx-1"


def test_configure_logging_keeps_a_single_json_handler() -> None:
    configure_logging("INFO")
    configure_logging("DEBUG")

    handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, logging.StreamHandler)
        and isinstance(handler.formatter, JsonFormatter)
    ]
    assert len(handlers) == 1


def test_configure_logging_routes_uvicorn_loggers_through_json_handler() -> None:
    configure_logging("INFO")

    access = logging.getLogger("uvicorn.access")
    assert access.handlers == []
    assert access.propagate is True
    assert access.level == logging.WARNING

    error = logging.getLogger("uvicorn.error")
    assert error.handlers == []
    assert error.propagate is True
