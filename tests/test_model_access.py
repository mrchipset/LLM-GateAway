from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.providers.base import ProviderName
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.storage.repositories import Tenant
from support import CapturingUsageRepository, FrozenClock, seed_api_key, seed_model

ALLOWED_MODEL = "fake-allowed"
OTHER_MODEL = "fake-other"
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _master(settings: Settings) -> str:
    return settings.master_key.get_secret_value()


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _error(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    error = body["error"]
    assert isinstance(error, dict)
    return error


async def _setup(
    make_container: Callable[..., Container],
    settings: Settings,
    *,
    usage: CapturingUsageRepository | None = None,
) -> tuple[Container, UUID, str]:
    clock = FrozenClock(NOW)
    container = make_container(
        settings,
        clock=clock,
        providers=ProviderRegistry({ProviderName.FAKE: FakeProvider(clock=clock)}),
        usage=usage,
    )
    await seed_model(container, model_id=ALLOWED_MODEL)
    await seed_model(container, model_id=OTHER_MODEL)
    tenant = await seed_tenant(container, name="access-tenant")
    secret = await seed_api_key(container, tenant_id=tenant.id)
    return container, tenant.id, secret


async def seed_tenant(container: Container, *, name: str) -> Tenant:
    return await container.tenants.create_tenant(
        Tenant(id=uuid4(), name=name, created_at=container.clock.now())
    )


async def _chat(client: httpx.AsyncClient, secret: str, model: str) -> httpx.Response:
    return await client.post(
        "/v1/chat/completions",
        headers=_auth(secret),
        json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
    )


async def _put_access(
    client: httpx.AsyncClient,
    settings: Settings,
    tenant_id: object,
    *,
    mode: str,
    model_ids: list[str],
) -> httpx.Response:
    return await client.put(
        f"/api/v1/tenants/{tenant_id}/model-access",
        headers=_auth(_master(settings)),
        json={"mode": mode, "model_ids": model_ids},
    )


async def test_tenant_without_an_explicit_policy_can_use_every_model(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, _, secret = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await _chat(client, secret, OTHER_MODEL)

    assert response.status_code == 200


async def test_allowlist_denies_an_unlisted_model_without_recording_usage(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    usage = CapturingUsageRepository()
    container, tenant_id, secret = await _setup(make_container, settings, usage=usage)

    async with make_client(settings, container) as client:
        saved = await _put_access(
            client,
            settings,
            tenant_id,
            mode="allowlist",
            model_ids=[ALLOWED_MODEL],
        )
        denied = await _chat(client, secret, OTHER_MODEL)
        allowed = await _chat(client, secret, ALLOWED_MODEL)

    assert saved.status_code == 200
    assert denied.status_code == 403
    assert _error(denied)["code"] == "model_not_allowed"
    assert allowed.status_code == 200
    assert [record.model_id for record in usage.records] == [ALLOWED_MODEL]


async def test_models_endpoint_returns_only_allowed_models(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, tenant_id, secret = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        await _put_access(
            client,
            settings,
            tenant_id,
            mode="allowlist",
            model_ids=[ALLOWED_MODEL],
        )
        response = await client.get("/v1/models", headers=_auth(secret))

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [ALLOWED_MODEL]


async def test_empty_allowlist_blocks_every_model(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, tenant_id, secret = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        await _put_access(client, settings, tenant_id, mode="allowlist", model_ids=[])
        chat = await _chat(client, secret, ALLOWED_MODEL)
        models = await client.get("/v1/models", headers=_auth(secret))

    assert chat.status_code == 403
    assert _error(chat)["code"] == "model_not_allowed"
    assert models.status_code == 200
    assert models.json()["data"] == []


async def test_put_replaces_the_previous_set(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, tenant_id, _ = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        first = await _put_access(
            client,
            settings,
            tenant_id,
            mode="allowlist",
            model_ids=[ALLOWED_MODEL, OTHER_MODEL, ALLOWED_MODEL],
        )
        second = await _put_access(
            client,
            settings,
            tenant_id,
            mode="allowlist",
            model_ids=[OTHER_MODEL],
        )
        fetched = await client.get(
            f"/api/v1/tenants/{tenant_id}/model-access",
            headers=_auth(_master(settings)),
        )

    assert first.status_code == 200
    assert first.json()["model_ids"] == sorted([ALLOWED_MODEL, OTHER_MODEL])
    assert second.status_code == 200
    assert second.json()["model_ids"] == [OTHER_MODEL]
    assert fetched.status_code == 200
    assert fetched.json()["mode"] == "allowlist"
    assert fetched.json()["model_ids"] == [OTHER_MODEL]


async def test_switching_back_to_all_clears_the_allowlist(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, tenant_id, secret = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        await _put_access(
            client,
            settings,
            tenant_id,
            mode="allowlist",
            model_ids=[ALLOWED_MODEL],
        )
        reset = await _put_access(
            client,
            settings,
            tenant_id,
            mode="all",
            model_ids=[ALLOWED_MODEL],
        )
        chat = await _chat(client, secret, OTHER_MODEL)
        tenants = await client.get("/api/v1/tenants", headers=_auth(_master(settings)))

    assert reset.status_code == 200
    assert reset.json() == {
        "tenant_id": str(tenant_id),
        "mode": "all",
        "model_ids": [],
    }
    assert chat.status_code == 200
    assert tenants.json()["items"][0]["model_access_mode"] == "all"


async def test_unknown_model_in_the_allowlist_is_rejected(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, tenant_id, _ = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await _put_access(
            client,
            settings,
            tenant_id,
            mode="allowlist",
            model_ids=[ALLOWED_MODEL, "does-not-exist"],
        )
        fetched = await client.get(
            f"/api/v1/tenants/{tenant_id}/model-access",
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 404
    assert _error(response)["code"] == "model_not_found"
    # The failed replacement must not partially apply.
    assert fetched.json()["mode"] == "all"
    assert fetched.json()["model_ids"] == []


async def test_unknown_tenant_returns_404(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, _, _ = await _setup(make_container, settings)
    missing = uuid4()

    async with make_client(settings, container) as client:
        response = await _put_access(
            client,
            settings,
            missing,
            mode="allowlist",
            model_ids=[ALLOWED_MODEL],
        )

    assert response.status_code == 404
    assert _error(response)["code"] == "tenant_not_found"


async def test_invalid_mode_is_rejected(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, tenant_id, _ = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await client.put(
            f"/api/v1/tenants/{tenant_id}/model-access",
            headers=_auth(_master(settings)),
            json={"mode": "deny-all", "model_ids": []},
        )

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_request_body"


@pytest.mark.parametrize("model_ids", [["  "], [""], [ALLOWED_MODEL, ""]])
async def test_blank_model_ids_are_rejected(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    model_ids: list[str],
) -> None:
    container, tenant_id, _ = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        response = await _put_access(
            client,
            settings,
            tenant_id,
            mode="allowlist",
            model_ids=model_ids,
        )

    assert response.status_code == 400
