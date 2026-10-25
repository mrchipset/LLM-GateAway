from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx

from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.storage.repositories import Tenant
from support import FrozenClock, seed_tenant, seed_usage

BASE = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _master(settings: Settings) -> str:
    return settings.master_key.get_secret_value()


def _error(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    error = body["error"]
    assert isinstance(error, dict)
    return error


async def _seed(container: Container) -> tuple[Tenant, Tenant]:
    tenant_a = await seed_tenant(container, name="tenant-a")
    tenant_b = await seed_tenant(container, name="tenant-b")
    api_key_id = uuid4()
    await seed_usage(
        container,
        tenant_id=tenant_a.id,
        api_key_id=api_key_id,
        model_id="model-a",
        created_at=BASE + timedelta(hours=1),
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=2,
        request_id="req-1",
    )
    await seed_usage(
        container,
        tenant_id=tenant_a.id,
        api_key_id=api_key_id,
        model_id="model-b",
        created_at=BASE + timedelta(hours=2),
        prompt_tokens=20,
        completion_tokens=10,
        cached_tokens=0,
        request_id="req-2",
    )
    await seed_usage(
        container,
        tenant_id=tenant_b.id,
        api_key_id=api_key_id,
        model_id="model-a",
        created_at=BASE + timedelta(hours=3),
        prompt_tokens=7,
        completion_tokens=3,
        cached_tokens=1,
        request_id="req-3",
    )
    return tenant_a, tenant_b


async def test_usage_summary_returns_totals_and_by_model(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    await _seed(container)

    async with make_client(settings, container) as client:
        response = await client.get(
            "/api/v1/usage/summary",
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["prompt_tokens"] == 37
    assert body["completion_tokens"] == 18
    assert body["cached_tokens"] == 3
    assert body["total_tokens"] == 55
    assert body["requests"] == 3
    assert body["requests"] == sum(item["requests"] for item in body["by_model"])
    for field in ("prompt_tokens", "completion_tokens", "cached_tokens", "total_tokens"):
        assert body[field] == sum(item[field] for item in body["by_model"])
    assert [item["model_id"] for item in body["by_model"]] == ["model-b", "model-a"]
    model_a = body["by_model"][1]
    assert model_a == {
        "model_id": "model-a",
        "provider": "fake",
        "prompt_tokens": 17,
        "completion_tokens": 8,
        "cached_tokens": 3,
        "total_tokens": 25,
        "requests": 2,
    }


async def test_usage_summary_filters_by_tenant_and_model(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant_a, tenant_b = await _seed(container)
    master = _auth(_master(settings))

    async with make_client(settings, container) as client:
        tenant_page = await client.get(
            f"/api/v1/usage/summary?tenant_id={tenant_a.id}",
            headers=master,
        )
        tenant_b_page = await client.get(
            f"/api/v1/usage/summary?tenant_id={tenant_b.id}",
            headers=master,
        )
        model_page = await client.get(
            "/api/v1/usage/summary?model_id=model-a",
            headers=master,
        )
        missing_page = await client.get(
            "/api/v1/usage/summary?model_id=missing-model",
            headers=master,
        )

    body = tenant_page.json()
    assert body["total_tokens"] == 45
    assert body["requests"] == 2
    assert [item["model_id"] for item in body["by_model"]] == ["model-b", "model-a"]

    assert tenant_b_page.json()["total_tokens"] == 10
    assert tenant_b_page.json()["requests"] == 1

    assert model_page.json()["total_tokens"] == 25
    assert model_page.json()["requests"] == 2
    assert [item["model_id"] for item in model_page.json()["by_model"]] == ["model-a"]

    assert missing_page.json() == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
        "requests": 0,
        "by_model": [],
    }


async def test_usage_summary_since_until_is_half_open(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    await _seed(container)
    master = _auth(_master(settings))
    boundary = (BASE + timedelta(hours=2)).isoformat().replace("+00:00", "Z")

    async with make_client(settings, container) as client:
        since_page = await client.get(
            f"/api/v1/usage/summary?since={boundary}",
            headers=master,
        )
        until_page = await client.get(
            f"/api/v1/usage/summary?until={boundary}",
            headers=master,
        )

    assert since_page.json()["requests"] == 2
    assert since_page.json()["total_tokens"] == 40

    assert until_page.json()["requests"] == 1
    assert until_page.json()["total_tokens"] == 15


async def test_usage_summary_rejects_naive_and_inverted_windows(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    master = _auth(_master(settings))

    async with make_client(settings, container) as client:
        naive_since = await client.get(
            "/api/v1/usage/summary?since=2026-01-02T00:00:00",
            headers=master,
        )
        naive_until = await client.get(
            "/api/v1/usage/summary?until=2026-01-02T00:00:00",
            headers=master,
        )
        inverted = await client.get(
            "/api/v1/usage/summary?since=2026-01-03T00:00:00Z&until=2026-01-02T00:00:00Z",
            headers=master,
        )

    assert naive_since.status_code == 400
    assert _error(naive_since)["code"] == "invalid_request_body"
    assert _error(naive_since)["param"] == "since"

    assert naive_until.status_code == 400
    assert _error(naive_until)["param"] == "until"

    assert inverted.status_code == 400
    assert _error(inverted)["code"] == "invalid_request_body"


async def test_usage_summary_rejects_unknown_tenant(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    unknown = uuid4()

    async with make_client(settings, container) as client:
        response = await client.get(
            f"/api/v1/usage/summary?tenant_id={unknown}",
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 404
    error = _error(response)
    assert error["code"] == "tenant_not_found"
    assert error["param"] == "tenant_id"
    assert str(unknown) in error["message"]


async def test_usage_summary_requires_the_master_key(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())

    async with make_client(settings, container) as client:
        response = await client.get("/api/v1/usage/summary")

    assert response.status_code == 401
    assert _error(response)["code"] == "master_key_required"
