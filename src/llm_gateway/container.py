from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Request

from llm_gateway.clock import Clock, SystemClock
from llm_gateway.config import Settings

ReadinessCheck = Callable[[], Awaitable[tuple[str, bool]]]


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    checks: dict[str, str]


@dataclass(slots=True)
class Container:
    settings: Settings
    clock: Clock
    readiness_checks: tuple[ReadinessCheck, ...] = ()

    async def check_readiness(self) -> ReadinessReport:
        results = await asyncio.gather(
            *(check() for check in self.readiness_checks),
            return_exceptions=True,
        )

        checks: dict[str, str] = {}
        for check, result in zip(self.readiness_checks, results, strict=True):
            if isinstance(result, BaseException):
                checks[_check_name(check)] = "error"
                continue
            name, ok = result
            checks[name] = "ok" if ok else "error"

        return ReadinessReport(
            ready=all(status == "ok" for status in checks.values()),
            checks=checks,
        )

    async def aclose(self) -> None:
        return None


def _check_name(check: ReadinessCheck) -> str:
    name = getattr(check, "__name__", None)
    return name if isinstance(name, str) else "readiness_check"


def get_container(request: Request) -> Container:
    container = request.app.state.container
    if not isinstance(container, Container):
        raise RuntimeError("application container is not configured")
    return container


def build_container(settings: Settings) -> Container:
    return Container(settings=settings, clock=SystemClock())
