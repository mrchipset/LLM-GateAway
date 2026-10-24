from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from random import Random

Sleeper = Callable[[float], Awaitable[None]]


async def asyncio_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be greater than 0")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be at least base_delay_seconds")

    def delay_for_attempt(self, retry_number: int, rng: Random) -> float:
        if retry_number < 1:
            raise ValueError("retry_number must be at least 1")
        cap = min(
            self.max_delay_seconds,
            self.base_delay_seconds * 2 ** (retry_number - 1),
        )
        return rng.uniform(0, cap)
