from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from llm_gateway.request_context import get_request_id

_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "master_key",
        "password",
        "secret",
        "token",
        "key_hash",
    }
)

_RESERVED_RECORD_ATTRIBUTES = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

_RESERVED_PAYLOAD_KEYS = frozenset({"ts", "level", "logger", "message", "request_id", "exception"})


def _redact(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            redacted[key] = "[redacted]" if key.lower() in _SENSITIVE_KEYS else _redact(raw_value)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {}
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRIBUTES or key in _RESERVED_PAYLOAD_KEYS:
                continue
            payload[key] = "[redacted]" if key.lower() in _SENSITIVE_KEYS else _redact(value)

        payload["ts"] = (
            datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        payload["level"] = record.levelname
        payload["logger"] = record.name
        payload["message"] = record.getMessage()

        request_id = getattr(record, "request_id", None)
        if not isinstance(request_id, str):
            request_id = get_request_id()
        if request_id is not None:
            payload["request_id"] = request_id

        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, logging.StreamHandler) and isinstance(
            handler.formatter, JsonFormatter
        ):
            root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
