from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from llm_gateway.config import Environment, RateLimitBackend, Settings
from llm_gateway.container import build_container

REDIS_URL = "redis://127.0.0.1:6379/0"


def _settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": Environment.TEST,
        "master_key": "test-master-key-0123456789abcdef",
    }
    values.update(overrides)
    return Settings(**values)


def test_redis_backend_requires_a_url() -> None:
    with pytest.raises(ValidationError, match="redis_url"):
        _settings(rate_limit_backend=RateLimitBackend.REDIS)


async def test_fail_open_does_not_gate_readiness_on_redis() -> None:
    settings = _settings(
        rate_limit_backend=RateLimitBackend.REDIS,
        redis_url=REDIS_URL,
        rate_limit_fail_open=True,
    )
    container = build_container(settings)
    try:
        assert all(check.name != "rate_limiter" for check in container.readiness_checks)
    finally:
        await container.aclose()


async def test_fail_closed_adds_a_redis_readiness_check() -> None:
    settings = _settings(
        rate_limit_backend=RateLimitBackend.REDIS,
        redis_url=REDIS_URL,
        rate_limit_fail_open=False,
    )
    container = build_container(settings)
    try:
        assert [check.name for check in container.readiness_checks] == ["rate_limiter"]
    finally:
        await container.aclose()
