from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from llm_gateway.metrics import current_metrics
from llm_gateway.telemetry import Telemetry, extract_trace_context

REQUEST_ID_HEADER = "x-request-id"

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

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


def _route_label(scope: Scope) -> str:
    """Return the matched route template, never the concrete path.

    Concrete paths contain ids and would explode metric cardinality; unmatched
    requests collapse into a single label for the same reason.
    """
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else "unmatched"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, telemetry: Telemetry | None = None) -> None:
        self.app = app
        self._telemetry = (
            telemetry
            if telemetry is not None
            else Telemetry(tracer=trace.get_tracer("llm_gateway.request"))
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _resolve_incoming_request_id(scope)
        _bind_request_id(scope, request_id)
        span = self._start_span(scope)

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
        try:
            with trace.use_span(span, end_on_exit=False), request_id_scope(request_id):
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
        finally:
            elapsed_seconds = perf_counter() - start
            route = _route_label(scope)
            instruments = current_metrics()
            instruments.requests.add(
                1,
                {
                    "route": route,
                    "method": scope.get("method", ""),
                    "status_code": str(status_code),
                },
            )
            instruments.request_duration.record(elapsed_seconds, {"route": route})
            span.set_attribute("http.response.status_code", status_code)
            if client_disconnected:
                span.set_attribute("llm.client_disconnected", True)
            span.set_attribute("llm.duration_ms", round(elapsed_seconds * 1000, 2))
            if status_code >= 500:
                span.set_status(Status(StatusCode.ERROR))
            span.end()

    def _start_span(self, scope: Scope) -> Span:
        carrier = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope.get("headers", [])
        }
        return self._telemetry.tracer.start_span(
            "http.server",
            context=extract_trace_context(carrier),
            kind=SpanKind.SERVER,
            attributes={
                "http.request.method": scope.get("method", ""),
                "url.path": scope.get("path", ""),
            },
        )
