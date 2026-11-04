"""Track in-flight HTTP requests so shutdown can wait for them to finish.

The tracker is owned by the container, not by a module global, so tests and
multiple app instances each get isolated accounting. All methods are called on
the application's event loop; the synchronous start/finish pair never awaits,
which keeps the counter consistent between await points.
"""

from __future__ import annotations

import asyncio

from starlette.types import ASGIApp, Receive, Scope, Send


class InFlightTracker:
    """Count active HTTP requests and signal when the last one finishes."""

    def __init__(self) -> None:
        self._active = 0
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def active(self) -> int:
        return self._active

    def started(self) -> None:
        self._active += 1
        self._idle.clear()

    def finished(self) -> None:
        # A stray finish without a matching start must not corrupt the counter.
        if self._active == 0:
            return
        self._active -= 1
        if self._active == 0:
            self._idle.set()

    async def wait_for_idle(self, timeout: float) -> bool:  # noqa: ASYNC109 - timeout is part of the public API
        """Return True once no requests are active, or False when timed out.

        A non-positive timeout polls the counter once and returns immediately so
        shutdown with grace disabled never yields to the event loop.
        """
        if self._active == 0:
            return True
        if timeout <= 0:
            return False
        try:
            await asyncio.wait_for(self._idle.wait(), timeout)
        except TimeoutError:
            return False
        return self._active == 0


class InFlightMiddleware:
    """Pure ASGI middleware that holds a request in-flight until its body drains.

    The wrapped app is awaited to completion, so a streaming response stays
    counted until the last body chunk is sent. The decrement lives in ``finally``
    to cover client disconnects and exceptions raised further down the stack.
    """

    def __init__(self, app: ASGIApp, *, tracker: InFlightTracker) -> None:
        self.app = app
        self._tracker = tracker

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        self._tracker.started()
        try:
            await self.app(scope, receive, send)
        finally:
            self._tracker.finished()


__all__ = ["InFlightMiddleware", "InFlightTracker"]
