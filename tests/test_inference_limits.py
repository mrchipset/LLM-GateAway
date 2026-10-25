from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx

from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.providers.base import ProviderName
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.storage.repositories import Tenant
from support import (
    CapturingUsageRepository,
    FrozenClock,
    seed_api_key,
    seed_model,
    seed_tenant,
    seed_usage,
)

FAKE_MODEL = "fake-model"
UPSTREAM_MODEL = "upstream-fake-model"
USER_MESSAGE = {"role": "user", "content": "hello"}


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _master(settings: Settings) -> str:
    return settings.master_key.get_secret_value()


def _payload() -> dict[str, object]:
    return {"model": FAKE_MODEL, "messages": [USER_MESSAGE]}


def _error(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    error = body["error"]
    assert isinstance(error, dict)
    return error


async def _setup(
    make_container: Callable[..., Container],
    settings: Settings,
    *,
    clock: FrozenClock | None = None,
    monthly_token_quota: int | None = None,
    requests_per_minute: int | None = None,
    usage: CapturingUsageRepository | None = None,
) -> tuple[Container, str, Tenant]:
    resolved_clock = clock if clock is not None else FrozenClock()
    container = make_container(
        settings,
        providers=ProviderRegistry({ProviderName.FAKE: FakeProvider(clock=resolved_clock)}),
        clock=resolved_clock,
        usage=usage,
    )
    tenant = await seed_tenant(
        container,
        monthly_token_quota=monthly_token_quota,
        requests_per_minute=requests_per_minute,
    )
    await seed_model(
        container,
        model_id=FAKE_MODEL,
        provider=ProviderName.FAKE,
        upstream_model=UPSTREAM_MODEL,
    )
    secret = await seed_api_key(container, tenant_id=tenant.id)
    return container, secret, tenant


async def test_request_rate_limit_blocks_third_request_and_isolates_tenants(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    capture = CapturingUsageRepository()
    container, secret, tenant = await _setup(
        make_container,
        settings,
        requests_per_minute=2,
        usage=capture,
    )
    other_tenant = await seed_tenant(container, name="other-tenant")
    other_secret = await seed_api_key(container, tenant_id=other_tenant.id)

    async with make_client(settings, container) as client:
        first = await client.post("/v1/chat/completions", json=_payload(), headers=_auth(secret))
        second = await client.post("/v1/chat/completions", json=_payload(), headers=_auth(secret))
        third = await client.post("/v1/chat/completions", json=_payload(), headers=_auth(secret))
        models = await client.get("/v1/models", headers=_auth(secret))
        other = await client.post(
            "/v1/chat/completions",
            json=_payload(),
            headers=_auth(other_secret),
        )
        admin = await client.get(
            "/api/v1/tenants",
            headers=_auth(_master(settings)),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert _error(third)["code"] == "rate_limited"
    assert _error(third)["type"] == "rate_limit_error"
    retry_after = int(third.headers["retry-after"])
    assert 1 <= retry_after <= 60
    limited_tenant_records = [record for record in capture.records if record.tenant_id == tenant.id]
    assert len(limited_tenant_records) == 2

    assert models.status_code == 200
    assert other.status_code == 200
    assert admin.status_code == 200


async def test_monthly_quota_blocks_when_usage_reaches_quota(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    capture = CapturingUsageRepository()
    container, secret, tenant = await _setup(
        make_container,
        settings,
        monthly_token_quota=10,
        usage=capture,
    )
    await seed_usage(
        container,
        tenant_id=tenant.id,
        api_key_id=uuid4(),
        model_id=FAKE_MODEL,
        prompt_tokens=10,
        completion_tokens=5,
    )

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json=_payload(),
            headers=_auth(secret),
        )

    assert response.status_code == 429
    error = _error(response)
    assert error["code"] == "tenant_quota_exceeded"
    assert error["type"] == "insufficient_quota"
    assert len(capture.records) == 1


async def test_monthly_quota_allows_request_below_quota(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    capture = CapturingUsageRepository()
    container, secret, tenant = await _setup(
        make_container,
        settings,
        monthly_token_quota=100,
        usage=capture,
    )
    await seed_usage(
        container,
        tenant_id=tenant.id,
        api_key_id=uuid4(),
        model_id=FAKE_MODEL,
        prompt_tokens=10,
        completion_tokens=5,
    )

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json=_payload(),
            headers=_auth(secret),
        )

    assert response.status_code == 200
    assert len(capture.records) == 2


async def test_monthly_quota_ignores_previous_month_usage(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    capture = CapturingUsageRepository()
    clock = FrozenClock(datetime(2026, 2, 10, 12, 0, tzinfo=UTC))
    container, secret, tenant = await _setup(
        make_container,
        settings,
        clock=clock,
        monthly_token_quota=50,
        usage=capture,
    )
    await seed_usage(
        container,
        tenant_id=tenant.id,
        api_key_id=uuid4(),
        model_id=FAKE_MODEL,
        created_at=datetime(2026, 1, 31, 23, 59, tzinfo=UTC),
        prompt_tokens=80,
        completion_tokens=20,
    )

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json=_payload(),
            headers=_auth(secret),
        )

    assert response.status_code == 200
    assert len(capture.records) == 2


async def test_tenant_without_limits_is_not_blocked(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container, secret, _tenant = await _setup(make_container, settings)

    async with make_client(settings, container) as client:
        responses = [
            await client.post("/v1/chat/completions", json=_payload(), headers=_auth(secret))
            for _ in range(3)
        ]

    assert [response.status_code for response in responses] == [200, 200, 200]


async def test_quota_rejection_does_not_consume_rate_limit_budget(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    capture = CapturingUsageRepository()
    container, secret, tenant = await _setup(
        make_container,
        settings,
        monthly_token_quota=10,
        requests_per_minute=1,
        usage=capture,
    )
    await seed_usage(
        container,
        tenant_id=tenant.id,
        api_key_id=uuid4(),
        model_id=FAKE_MODEL,
        prompt_tokens=10,
        completion_tokens=5,
    )

    async with make_client(settings, container) as client:
        blocked = await client.post(
            "/v1/chat/completions",
            json=_payload(),
            headers=_auth(secret),
        )
        cleared = await client.patch(
            f"/api/v1/tenants/{tenant.id}",
            json={"monthly_token_quota": None},
            headers=_auth(_master(settings)),
        )
        allowed = await client.post(
            "/v1/chat/completions",
            json=_payload(),
            headers=_auth(secret),
        )

    assert blocked.status_code == 429
    assert _error(blocked)["code"] == "tenant_quota_exceeded"
    assert cleared.status_code == 200
    assert allowed.status_code == 200


async def test_quota_counts_total_tokens_not_prompt_tokens(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    capture = CapturingUsageRepository()
    container, secret, tenant = await _setup(
        make_container,
        settings,
        monthly_token_quota=10,
        usage=capture,
    )
    await seed_usage(
        container,
        tenant_id=tenant.id,
        api_key_id=uuid4(),
        model_id=FAKE_MODEL,
        prompt_tokens=1,
        completion_tokens=0,
        total_tokens=50,
    )

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json=_payload(),
            headers=_auth(secret),
        )

    assert response.status_code == 429
    assert _error(response)["code"] == "tenant_quota_exceeded"


async def test_quota_does_not_block_small_total_tokens_with_large_prompt(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    capture = CapturingUsageRepository()
    container, secret, tenant = await _setup(
        make_container,
        settings,
        monthly_token_quota=10,
        usage=capture,
    )
    await seed_usage(
        container,
        tenant_id=tenant.id,
        api_key_id=uuid4(),
        model_id=FAKE_MODEL,
        prompt_tokens=50,
        completion_tokens=0,
        total_tokens=4,
    )

    async with make_client(settings, container) as client:
        response = await client.post(
            "/v1/chat/completions",
            json=_payload(),
            headers=_auth(secret),
        )

    assert response.status_code == 200
