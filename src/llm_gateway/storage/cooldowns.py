"""Shared deployment cooldown state.

The router asks this store two questions on every attempt: is this deployment
cooling down, and when does the cooldown end. A failure at or above the
threshold opens the cooldown for ``cooldown_seconds``; a success clears both the
failure count and any cooldown.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from llm_gateway.logging import get_logger
from llm_gateway.metrics import current_metrics

logger = get_logger(__name__)

_REDIS_FAILURE_SCRIPT = """
local failures = redis.call('INCR', KEYS[1])
redis.call('PEXPIRE', KEYS[1], ARGV[1])
if failures >= tonumber(ARGV[2]) then
  redis.call('DEL', KEYS[1])
  redis.call('SET', KEYS[2], ARGV[3], 'PX', ARGV[1])
  return 1
end
return 0
"""


class DeploymentHealth(Protocol):
    async def available(self, deployment_id: UUID, now: datetime) -> bool: ...

    async def cooldown_until(self, deployment_id: UUID) -> datetime | None: ...

    async def record_success(self, deployment_id: UUID) -> None: ...

    async def record_failure(self, deployment_id: UUID, now: datetime) -> bool: ...


@dataclass(slots=True)
class InMemoryDeploymentHealth:
    """Process-local health; each worker learns about failures on its own."""

    threshold: int = 3
    cooldown_seconds: int = 30
    _failures: dict[UUID, int] = field(default_factory=dict)
    _cooldown_until: dict[UUID, datetime] = field(default_factory=dict)

    async def available(self, deployment_id: UUID, now: datetime) -> bool:
        until = self._cooldown_until.get(deployment_id)
        return until is None or now >= until

    async def cooldown_until(self, deployment_id: UUID) -> datetime | None:
        return self._cooldown_until.get(deployment_id)

    async def record_success(self, deployment_id: UUID) -> None:
        self._failures.pop(deployment_id, None)
        self._cooldown_until.pop(deployment_id, None)

    async def record_failure(self, deployment_id: UUID, now: datetime) -> bool:
        """Return True when this failure triggered a cooldown."""
        failures = self._failures.get(deployment_id, 0) + 1
        if failures < self.threshold:
            self._failures[deployment_id] = failures
            return False
        self._failures[deployment_id] = 0
        self._cooldown_until[deployment_id] = now + timedelta(seconds=self.cooldown_seconds)
        return True


class RedisDeploymentHealth:
    """Cooldown state shared by every gateway process.

    Failure counters expire after one cooldown window so a deployment that fails
    once an hour never accumulates to the threshold. Redis errors degrade to
    "available" and are logged and counted: routing must keep working when the
    health backend is down, and the failure path already has its own retries.
    """

    def __init__(
        self,
        *,
        client: Redis,
        threshold: int = 3,
        cooldown_seconds: int = 30,
        key_prefix: str = "llm-gateway:health",
        timeout_seconds: float = 0.2,
    ) -> None:
        if threshold < 1 or cooldown_seconds < 1:
            raise ValueError("threshold and cooldown_seconds must be >= 1")
        self._client = client
        self._threshold = threshold
        self._cooldown_seconds = cooldown_seconds
        self._key_prefix = key_prefix
        self._timeout_seconds = timeout_seconds
        self._failure_script = client.register_script(_REDIS_FAILURE_SCRIPT)

    def _failure_key(self, deployment_id: UUID) -> str:
        return f"{self._key_prefix}:fail:{deployment_id}"

    def _cooldown_key(self, deployment_id: UUID) -> str:
        return f"{self._key_prefix}:until:{deployment_id}"

    async def available(self, deployment_id: UUID, now: datetime) -> bool:
        until = await self.cooldown_until(deployment_id)
        return until is None or now >= until

    async def cooldown_until(self, deployment_id: UUID) -> datetime | None:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                raw = await self._client.get(self._cooldown_key(deployment_id))
        except TimeoutError:
            self._degraded("timeout")
            return None
        except (RedisError, OSError):
            self._degraded("error")
            return None
        if raw is None:
            return None
        return datetime.fromtimestamp(int(raw) / 1000, UTC)

    async def record_success(self, deployment_id: UUID) -> None:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                await self._client.delete(
                    self._failure_key(deployment_id),
                    self._cooldown_key(deployment_id),
                )
        except TimeoutError:
            self._degraded("timeout")
        except (RedisError, OSError):
            self._degraded("error")

    async def record_failure(self, deployment_id: UUID, now: datetime) -> bool:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                opened = await self._failure_script(
                    keys=[
                        self._failure_key(deployment_id),
                        self._cooldown_key(deployment_id),
                    ],
                    args=[
                        self._cooldown_seconds * 1000,
                        self._threshold,
                        int((now + timedelta(seconds=self._cooldown_seconds)).timestamp() * 1000),
                    ],
                )
        except TimeoutError:
            self._degraded("timeout")
            return False
        except (RedisError, OSError):
            self._degraded("error")
            return False
        return int(opened) == 1

    def _degraded(self, reason: str) -> None:
        current_metrics().cooldown_degraded.add(1, {"reason": reason})
        logger.warning("deployment_health_degraded", extra={"reason": reason})
