"""Reject oversized request bodies before they are parsed or forwarded.

Content-Length is checked up front; chunked bodies are counted as they stream so a client
cannot bypass the limit by omitting the header. The rejection uses the same error
envelope as the rest of the API and carries the request id when the outer middleware has
already assigned one.
"""

from __future__ import annotations

import json
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from llm_gateway.errors import ApiErrorCode
from llm_gateway.metrics import current_metrics


class BodyTooLargeError(Exception):
    pass


def _request_id(scope: Scope) -> str:
    state = scope.get("state")
    if isinstance(state, dict):
        stored = state.get("request_id")
        if isinstance(stored, str) and stored:
            return stored
    return uuid.uuid4().hex


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() != b"content-length":
            continue
        try:
            return int(value)
        except ValueError:
            return None
    return None


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared is not None and declared > self.max_bytes:
            await self._reject(scope, send)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLargeError:
            if response_started:
                return
            await self._reject(scope, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        request_id = _request_id(scope)
        current_metrics().rejections.add(1, {"reason": "request_too_large"})
        body = json.dumps(
            {
                "error": {
                    "message": f"Request body exceeds {self.max_bytes} bytes",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": ApiErrorCode.REQUEST_TOO_LARGE.value,
                    "request_id": request_id,
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"x-request-id", request_id.encode()),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


__all__ = ["BodyTooLargeError", "RequestBodyLimitMiddleware"]
