from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

_access_logger = logging.getLogger("llm_gateway.access")


def get_request_id() -> str | None:
    return _request_id_context.get()


@contextmanager
def request_id_scope(value: str) -> Iterator[None]:
    token = _request_id_context.set(value)
    try:
        yield
    finally:
        _request_id_context.reset(token)


def _resolve_incoming_request_id(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name.lower() != REQUEST_ID_HEADER.encode():
            continue
        try:
            candidate = value.decode("ascii")
        except UnicodeDecodeError:
            break
        if _REQUEST_ID_PATTERN.fullmatch(candidate):
            return candidate
        break
    return uuid.uuid4().hex


def _bind_request_id(scope: Scope, request_id: str) -> None:
    state = scope.get("state")
    if not isinstance(state, dict):
        state = {}
        scope["state"] = state
    state["request_id"] = request_id


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _resolve_incoming_request_id(scope)
        _bind_request_id(scope, request_id)

        status_code = 500
        client_disconnected = False
        response_started = False

        async def receive_with_disconnect() -> Message:
            nonlocal client_disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                client_disconnected = True
            return message

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, client_disconnected, response_started
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != REQUEST_ID_HEADER.encode()
                ]
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
                await send(message)
                response_started = True
                return

            try:
                await send(message)
            except BaseException:
                if response_started:
                    client_disconnected = True
                raise

        start = perf_counter()
        with request_id_scope(request_id):
            try:
                await self.app(scope, receive_with_disconnect, send_with_request_id)
            finally:
                _access_logger.info(
                    "request_completed",
                    extra={
                        "request_id": request_id,
                        "method": scope.get("method", ""),
                        "path": scope.get("path", ""),
                        "status_code": status_code,
                        "duration_ms": round((perf_counter() - start) * 1000, 2),
                        "client_disconnected": client_disconnected,
                    },
                )
