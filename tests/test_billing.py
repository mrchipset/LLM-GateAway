from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx

from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.providers.base import ProviderName
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Usage,
)
from llm_gateway.services.billing import (
    BillingAllowance,
    compute_usage_cost,
    split_allowance,
)
from llm_gateway.storage.repositories import ModelPrice, UsageRecord
from support import FrozenClock, seed_api_key, seed_model, seed_tenant, seed_usage

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
MODEL_ID = "priced-model"
PROMPT_TOKENS = 1000
CACHED_TOKENS = 200
COMPLETION_TOKENS = 500
TOTAL_TOKENS = PROMPT_TOKENS + COMPLETION_TOKENS


def _master(settings: Settings) -> str:
    return settings.master_key.get_secret_value()


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


class FixedUsageProvider:
    """Provider that returns deterministic usage so cost assertions are exact."""

    name = ProviderName.FAKE

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        self.calls += 1
        return ChatCompletionResponse(
            id="chatcmpl-fixed",
            created=1,
            model=upstream_model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=Usage.model_validate(
                {
                    "prompt_tokens": PROMPT_TOKENS,
                    "completion_tokens": COMPLETION_TOKENS,
                    "total_tokens": TOTAL_TOKENS,
                    "prompt_tokens_details": {"cached_tokens": CACHED_TOKENS},
                }
            ),
        )

    def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        raise NotImplementedError("streaming is not used in billing tests")

    async def aclose(self) -> None:
        return None


async def _price(
    container: Container,
    *,
    model_id: str = MODEL_ID,
    input_per_million: Decimal = Decimal("1"),
    cached_input_per_million: Decimal | None = Decimal("0.5"),
    output_per_million: Decimal = Decimal("2"),
    effective_from: datetime = NOW,
) -> ModelPrice:
    price = ModelPrice(
        id=uuid4(),
        model_id=model_id,
        input_per_million=input_per_million,
        cached_input_per_million=cached_input_per_million,
        output_per_million=output_per_million,
        currency="USD",
        effective_from=effective_from,
        created_at=NOW,
    )
    return await container.prices.create_price(price)


async def _stack(
    make_container: Callable[..., Container],
    settings: Settings,
    *,
    plan_tokens: int | None = None,
    allow_overage: bool = False,
    budget: Decimal | None = None,
    with_price: bool = True,
) -> tuple[Container, FixedUsageProvider, str]:
    provider = FixedUsageProvider()
    container = make_container(
        settings,
        clock=FrozenClock(NOW),
        providers=ProviderRegistry({ProviderName.FAKE: provider}),
    )
    await seed_model(container, model_id=MODEL_ID)
    tenant = await seed_tenant(
        container,
        name="billing-tenant",
        plan_tokens=plan_tokens,
        plan_allow_overage=allow_overage,
        monthly_cost_budget=budget,
    )
    secret = await seed_api_key(container, tenant_id=tenant.id)
    if with_price:
        await _price(container)
    return container, provider, secret


async def _chat(client: httpx.AsyncClient, secret: str) -> httpx.Response:
    return await client.post(
        "/v1/chat/completions",
        headers=_auth(secret),
        json={"model": MODEL_ID, "messages": [{"role": "user", "content": "hello"}]},
    )


# ---------------------------------------------------------------- pure math


def test_split_allowance_preserves_the_exact_total() -> None:
    parts = split_allowance((800, 200, 500), 1000)

    assert sum(parts) == 1000
    assert all(part <= bucket for part, bucket in zip(parts, (800, 200, 500), strict=True))


def test_split_allowance_handles_boundaries() -> None:
    assert split_allowance((800, 200, 500), 0) == (0, 0, 0)
    assert split_allowance((800, 200, 500), 1500) == (800, 200, 500)
    assert split_allowance((0, 0, 0), 10) == (0, 0, 0)


def test_unpriced_usage_has_no_money_but_counts_every_token_as_billable() -> None:
    cost = compute_usage_cost(
        prompt_tokens=PROMPT_TOKENS,
        cached_tokens=CACHED_TOKENS,
        completion_tokens=COMPLETION_TOKENS,
        allowance=None,
    )

    assert cost.covered_tokens == 0
    assert cost.billable_tokens == TOTAL_TOKENS
    assert cost.list_cost is None
    assert cost.billed_cost is None


def test_planned_usage_is_covered_and_only_the_excess_is_priced() -> None:
    allowance = BillingAllowance(
        price=ModelPrice(
            id=uuid4(),
            model_id=MODEL_ID,
            input_per_million=Decimal("1"),
            cached_input_per_million=Decimal("0.5"),
            output_per_million=Decimal("2"),
            currency="USD",
            effective_from=NOW,
            created_at=NOW,
        ),
        remaining_plan_tokens=1000,
    )

    cost = compute_usage_cost(
        prompt_tokens=PROMPT_TOKENS,
        cached_tokens=CACHED_TOKENS,
        completion_tokens=COMPLETION_TOKENS,
        allowance=allowance,
    )

    assert cost.covered_tokens == 1000
    assert cost.billable_tokens == 500
    assert cost.list_cost == Decimal("0.001900")
    assert cost.billed_cost == Decimal("0.000634")


def test_cached_price_falls_back_to_the_input_price() -> None:
    allowance = BillingAllowance(
        price=ModelPrice(
            id=uuid4(),
            model_id=MODEL_ID,
            input_per_million=Decimal("3"),
            cached_input_per_million=None,
            output_per_million=Decimal("3"),
            currency="USD",
            effective_from=NOW,
            created_at=NOW,
        ),
        remaining_plan_tokens=None,
    )

    cost = compute_usage_cost(
        prompt_tokens=10,
        cached_tokens=10,
        completion_tokens=0,
        allowance=allowance,
    )

    assert cost.billed_cost == Decimal("0.000030")


# ---------------------------------------------------------------- enforcement


async def test_tenant_without_plan_or_budget_needs_no_price(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, _, secret = await _stack(make_container, settings, with_price=False)

    async with make_client(settings, container) as client:
        response = await _chat(client, secret)

    assert response.status_code == 200
    records = await container.usage.summary_by_model(
        tenant_id=None, model_id=None, since=None, until=None
    )
    assert records[0].billable_tokens == TOTAL_TOKENS
    assert records[0].billed_cost == Decimal("0")


async def test_plan_covers_usage_and_bills_nothing(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret = await _stack(make_container, settings, plan_tokens=10_000)

    async with make_client(settings, container) as client:
        response = await _chat(client, secret)

    assert response.status_code == 200
    assert provider.calls == 1
    records = await container.usage.summary_by_model(
        tenant_id=None, model_id=None, since=None, until=None
    )
    assert records[0].covered_tokens == TOTAL_TOKENS
    assert records[0].billable_tokens == 0
    assert records[0].billed_cost == Decimal("0")
    assert records[0].list_cost == Decimal("0.001900")


async def test_exhausted_plan_blocks_before_the_upstream_call(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret = await _stack(make_container, settings, plan_tokens=1)
    tenant = (await container.tenants.list_tenants(limit=1, offset=0))[0][0]
    await seed_usage(
        container,
        tenant_id=tenant.id,
        api_key_id=(await container.api_keys.list_keys(limit=1, offset=0))[0][0].id,
        model_id=MODEL_ID,
        prompt_tokens=1,
        completion_tokens=0,
    )

    async with make_client(settings, container) as client:
        response = await _chat(client, secret)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "plan_allowance_exhausted"
    assert provider.calls == 0


async def test_overage_is_billed_when_allowed(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, _, secret = await _stack(
        make_container,
        settings,
        plan_tokens=1000,
        allow_overage=True,
    )

    async with make_client(settings, container) as client:
        response = await _chat(client, secret)

    assert response.status_code == 200
    records = await container.usage.summary_by_model(
        tenant_id=None, model_id=None, since=None, until=None
    )
    assert records[0].covered_tokens == 1000
    assert records[0].billable_tokens == 500
    assert records[0].billed_cost == Decimal("0.000634")


async def test_exhausted_budget_blocks(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret = await _stack(
        make_container,
        settings,
        allow_overage=True,
        budget=Decimal("0.001"),
    )
    tenant = (await container.tenants.list_tenants(limit=1, offset=0))[0][0]
    key = (await container.api_keys.list_keys(limit=1, offset=0))[0][0]
    await container.usage.record(
        UsageRecord(
            id=uuid4(),
            request_id="seeded",
            tenant_id=tenant.id,
            api_key_id=key.id,
            model_id=MODEL_ID,
            provider=ProviderName.FAKE,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cached_tokens=0,
            created_at=NOW,
            covered_tokens=0,
            billable_tokens=0,
            list_cost=Decimal("0.002"),
            billed_cost=Decimal("0.002"),
        )
    )

    async with make_client(settings, container) as client:
        response = await _chat(client, secret)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "budget_exceeded"
    assert provider.calls == 0


async def test_billed_tenant_without_a_price_fails_closed(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, provider, secret = await _stack(
        make_container, settings, plan_tokens=10_000, with_price=False
    )

    async with make_client(settings, container) as client:
        response = await _chat(client, secret)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_price_missing"
    assert provider.calls == 0


async def test_disabled_billing_lets_an_exhausted_plan_through(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    disabled = settings.model_copy(update={"billing_enabled": False})
    container, provider, secret = await _stack(make_container, disabled, plan_tokens=1)
    tenant = (await container.tenants.list_tenants(limit=1, offset=0))[0][0]
    key = (await container.api_keys.list_keys(limit=1, offset=0))[0][0]
    await seed_usage(
        container,
        tenant_id=tenant.id,
        api_key_id=key.id,
        model_id=MODEL_ID,
        prompt_tokens=1,
        completion_tokens=0,
    )

    async with make_client(disabled, container) as client:
        response = await _chat(client, secret)

    assert response.status_code == 200
    assert provider.calls == 1
    summary = await container.usage.summary_by_model(
        tenant_id=None, model_id=None, since=None, until=None
    )
    assert summary[0].total_tokens == 1 + TOTAL_TOKENS


async def test_disabled_billing_skips_the_price_lookup(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    disabled = settings.model_copy(update={"billing_enabled": False})
    container, provider, secret = await _stack(
        make_container, disabled, plan_tokens=10_000, with_price=False
    )

    async with make_client(disabled, container) as client:
        response = await _chat(client, secret)

    assert response.status_code == 200
    assert provider.calls == 1
    summary = await container.usage.summary_by_model(
        tenant_id=None, model_id=None, since=None, until=None
    )
    assert summary[0].total_tokens == TOTAL_TOKENS
    assert summary[0].list_cost == Decimal("0")
    assert summary[0].billed_cost == Decimal("0")


# ---------------------------------------------------------------- admin api


async def test_tenant_patch_sets_and_clears_billing_fields(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, _, _ = await _stack(make_container, settings, with_price=False)
    tenant = (await container.tenants.list_tenants(limit=1, offset=0))[0][0]

    async with make_client(settings, container) as client:
        updated = await client.patch(
            f"/api/v1/tenants/{tenant.id}",
            headers=_auth(_master(settings)),
            json={
                "plan_tokens": 5000,
                "plan_allow_overage": True,
                "monthly_cost_budget": "12.5",
            },
        )
        cleared = await client.patch(
            f"/api/v1/tenants/{tenant.id}",
            headers=_auth(_master(settings)),
            json={"plan_tokens": None, "monthly_cost_budget": None},
        )

    assert updated.status_code == 200
    assert updated.json()["plan_tokens"] == 5000
    assert updated.json()["plan_allow_overage"] is True
    assert Decimal(updated.json()["monthly_cost_budget"]) == Decimal("12.5")
    assert cleared.status_code == 200
    assert cleared.json()["plan_tokens"] is None
    assert cleared.json()["monthly_cost_budget"] is None
    assert cleared.json()["plan_allow_overage"] is True


async def test_billing_summary_reports_the_period(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, _, _ = await _stack(
        make_container,
        settings,
        plan_tokens=1000,
        allow_overage=True,
        budget=Decimal("1"),
    )
    tenant = (await container.tenants.list_tenants(limit=1, offset=0))[0][0]
    key = (await container.api_keys.list_keys(limit=1, offset=0))[0][0]
    await container.usage.record(
        UsageRecord(
            id=uuid4(),
            request_id="billing-seed",
            tenant_id=tenant.id,
            api_key_id=key.id,
            model_id=MODEL_ID,
            provider=ProviderName.FAKE,
            prompt_tokens=800,
            completion_tokens=500,
            total_tokens=1300,
            cached_tokens=0,
            created_at=NOW,
            covered_tokens=800,
            billable_tokens=500,
            list_cost=Decimal("0.001800"),
            billed_cost=Decimal("0.000500"),
        )
    )

    async with make_client(settings, container) as client:
        response = await client.get(
            f"/api/v1/tenants/{tenant.id}/billing",
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "USD"
    assert body["enabled"] is True
    assert body["used_tokens"] == 1300
    assert body["covered_tokens"] == 800
    assert body["billable_tokens"] == 500
    assert Decimal(body["list_cost"]) == Decimal("0.0018")
    assert Decimal(body["billed_cost"]) == Decimal("0.0005")
    assert Decimal(body["budget_remaining"]) == Decimal("0.9995")
    assert body["period_start"].startswith("2026-01-01T00:00:00")
    assert body["period_end"].startswith("2026-02-01T00:00:00")


async def test_price_api_appends_versions_and_rejects_duplicates(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, _, _ = await _stack(make_container, settings, with_price=False)
    path = f"/api/v1/models/{MODEL_ID}/prices"

    async with make_client(settings, container) as client:
        first = await client.post(
            path,
            headers=_auth(_master(settings)),
            json={"input_per_million": "1", "output_per_million": "2"},
        )
        second = await client.post(
            path,
            headers=_auth(_master(settings)),
            json={
                "input_per_million": "2",
                "cached_input_per_million": "0.5",
                "output_per_million": "4",
                "effective_from": "2026-02-01T00:00:00Z",
            },
        )
        duplicate = await client.post(
            path,
            headers=_auth(_master(settings)),
            json={
                "input_per_million": "1",
                "output_per_million": "1",
                "effective_from": "2026-02-01T00:00:00Z",
            },
        )
        listed = await client.get(path, headers=_auth(_master(settings)))
        missing_model = await client.get(
            "/api/v1/models/nope/prices", headers=_auth(_master(settings))
        )

    assert first.status_code == 201
    assert first.json()["currency"] == "USD"
    assert second.status_code == 201
    assert Decimal(second.json()["cached_input_per_million"]) == Decimal("0.5")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_price"
    assert [Decimal(item["input_per_million"]) for item in listed.json()["items"]] == [
        Decimal("2"),
        Decimal("1"),
    ]
    assert missing_model.status_code == 404


async def test_usage_summary_exposes_billing_fields(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, _, secret = await _stack(make_container, settings, plan_tokens=10_000)

    async with make_client(settings, container) as client:
        await _chat(client, secret)
        response = await client.get("/api/v1/usage/summary", headers=_auth(_master(settings)))

    body = response.json()
    assert body["covered_tokens"] == TOTAL_TOKENS
    assert body["billable_tokens"] == 0
    assert Decimal(body["list_cost"]) == Decimal("0.0019")
    assert Decimal(body["billed_cost"]) == 0
    assert body["by_model"][0]["covered_tokens"] == TOTAL_TOKENS


async def test_tenant_plan_is_enforced_from_the_database_state(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    """A plan set through PATCH takes effect on the next request."""

    container, _, secret = await _stack(make_container, settings, with_price=False)
    tenant = (await container.tenants.list_tenants(limit=1, offset=0))[0][0]
    key = (await container.api_keys.list_keys(limit=1, offset=0))[0][0]
    await seed_usage(
        container,
        tenant_id=tenant.id,
        api_key_id=key.id,
        model_id=MODEL_ID,
        prompt_tokens=1200,
        completion_tokens=300,
    )

    async with make_client(settings, container) as client:
        await _price(container)
        patched = await client.patch(
            f"/api/v1/tenants/{tenant.id}",
            headers=_auth(_master(settings)),
            json={"plan_tokens": 1000},
        )
        blocked = await _chat(client, secret)

    assert patched.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "plan_allowance_exhausted"


async def test_unknown_tenant_billing_is_404(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, _, _ = await _stack(make_container, settings, with_price=False)

    async with make_client(settings, container) as client:
        response = await client.get(
            f"/api/v1/tenants/{uuid4()}/billing",
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tenant_not_found"
