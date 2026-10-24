from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI

from llm_gateway.app import create_app
from llm_gateway.auth.dependencies import (
    AuthenticatedKey,
    require_api_key,
    require_master_key,
)
from llm_gateway.auth.keys import generate_api_key
from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.storage.memory import InMemoryApiKeyRepository, InMemoryModelRepository
from llm_gateway.storage.repositories import ApiKeyRecord

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FailingTouchRepository(InMemoryApiKeyRepository):
    async def touch_last_used(self, key_id: UUID, used_at: datetime) -> None:
        raise RuntimeError("storage unavailable")


def _container(
    settings: Settings,
    *,
    api_keys: InMemoryApiKeyRepository | None = None,
) -> Container:
    return Container(
        settings=settings,
        clock=FixedClock(NOW),
        api_keys=api_keys if api_keys is not None else InMemoryApiKeyRepository(),
        models=InMemoryModelRepository(),
        providers=ProviderRegistry({}),
    )


def _register_probes(app: FastAPI) -> None:
    @app.get("/probe/inference")
    async def inference(
        key: Annotated[AuthenticatedKey, Depends(require_api_key)],
    ) -> dict[str, str]:
        return {"key_id": str(key.record.id)}

    @app.get("/probe/admin")
    async def admin(_: Annotated[None, Depends(require_master_key)]) -> dict[str, str]:
        return {"status": "ok"}


@asynccontextmanager
async def _client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings=container.settings, container=container)
    _register_probes(app)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def _create_key(
    container: Container,
    *,
    expires_at: datetime | None = None,
    revoked: bool = False,
) -> tuple[str, ApiKeyRecord]:
    secret, record = generate_api_key(
        key_id=uuid4(),
        name="test key",
        now=NOW,
        expires_at=expires_at,
    )
    await container.api_keys.create_key(record)
    if revoked:
        await container.api_keys.revoke_key(record.id, NOW)
    return secret, record


def _error(response: httpx.Response) -> dict[str, object]:
    body = response.json()
    error = body["error"]
    assert isinstance(error, dict)
    return error


async def test_missing_header_returns_missing_api_key(settings: Settings) -> None:
    container = _container(settings)

    async with _client(container) as client:
        response = await client.get("/probe/inference")

    assert response.status_code == 401
    error = _error(response)
    assert error["code"] == "missing_api_key"
    assert error["type"] == "authentication_error"
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["x-request-id"]


async def test_valid_key_authenticates_and_records_last_used(settings: Settings) -> None:
    container = _container(settings)
    secret, record = await _create_key(container)

    async with _client(container) as client:
        response = await client.get(
            "/probe/inference",
            headers={"Authorization": f"Bearer {secret}"},
        )

    assert response.status_code == 200
    assert response.json() == {"key_id": str(record.id)}
    stored = await container.api_keys.get_key(record.id)
    assert stored is not None
    assert stored.last_used_at == NOW


async def test_unknown_key_returns_invalid_api_key(settings: Settings) -> None:
    container = _container(settings)

    async with _client(container) as client:
        response = await client.get(
            "/probe/inference",
            headers={"Authorization": "Bearer sk-gw-unknown"},
        )

    assert response.status_code == 401
    assert _error(response)["code"] == "invalid_api_key"


async def test_revoked_key_is_indistinguishable_from_unknown_key(settings: Settings) -> None:
    container = _container(settings)
    revoked_secret, _ = await _create_key(container, revoked=True)

    async with _client(container) as client:
        revoked = await client.get(
            "/probe/inference",
            headers={"Authorization": f"Bearer {revoked_secret}"},
        )
        unknown = await client.get(
            "/probe/inference",
            headers={"Authorization": "Bearer sk-gw-unknown"},
        )

    assert revoked.status_code == 401
    assert _error(revoked)["code"] == "invalid_api_key"
    assert _error(revoked)["message"] == _error(unknown)["message"]


async def test_expired_key_returns_invalid_api_key(settings: Settings) -> None:
    container = _container(settings)
    expired_secret, _ = await _create_key(container, expires_at=NOW - timedelta(seconds=1))

    async with _client(container) as client:
        response = await client.get(
            "/probe/inference",
            headers={"Authorization": f"Bearer {expired_secret}"},
        )

    assert response.status_code == 401
    assert _error(response)["code"] == "invalid_api_key"


async def test_master_key_is_rejected_on_inference_route(settings: Settings) -> None:
    container = _container(settings)
    master_key = settings.master_key.get_secret_value()

    async with _client(container) as client:
        response = await client.get(
            "/probe/inference",
            headers={"Authorization": f"Bearer {master_key}"},
        )

    assert response.status_code == 401
    assert _error(response)["code"] == "master_key_not_allowed"


async def test_admin_probe_requires_master_key(settings: Settings) -> None:
    container = _container(settings)
    normal_secret, _ = await _create_key(container)
    master_key = settings.master_key.get_secret_value()

    async with _client(container) as client:
        normal = await client.get(
            "/probe/admin",
            headers={"Authorization": f"Bearer {normal_secret}"},
        )
        missing = await client.get("/probe/admin")
        master = await client.get(
            "/probe/admin",
            headers={"Authorization": f"Bearer {master_key}"},
        )

    assert normal.status_code == 401
    assert _error(normal)["code"] == "invalid_api_key"
    assert missing.status_code == 401
    assert _error(missing)["code"] == "master_key_required"
    assert master.status_code == 200
    assert master.json() == {"status": "ok"}


async def test_last_used_failure_is_logged_and_does_not_fail_request(
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="llm_gateway.auth.dependencies")
    container = _container(settings, api_keys=FailingTouchRepository())
    secret, _ = await _create_key(container)

    async with _client(container) as client:
        response = await client.get(
            "/probe/inference",
            headers={"Authorization": f"Bearer {secret}"},
        )

    assert response.status_code == 200
    records = [
        record
        for record in caplog.records
        if record.name == "llm_gateway.auth.dependencies"
        and record.getMessage() == "api_key_touch_failed"
    ]
    assert len(records) == 1
    assert secret not in caplog.text
