from __future__ import annotations

import json
import logging
import re
from typing import cast

from llm_gateway.logging import JsonFormatter, configure_logging
from llm_gateway.request_context import request_id_scope

TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _render(**extra: object) -> dict[str, object]:
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
    formatted = JsonFormatter().format(record)
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
        nested={"api_key": "abc"},
        items=[{"token": "nested-token"}],
    )

    assert payload["authorization"] == "[redacted]"
    nested = payload["nested"]
    assert isinstance(nested, dict)
    assert nested["api_key"] == "[redacted]"
    items = payload["items"]
    assert isinstance(items, list)
    first = items[0]
    assert isinstance(first, dict)
    assert first["token"] == "[redacted]"


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
