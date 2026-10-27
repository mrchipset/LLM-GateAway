from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from llm_gateway.providers.base import ProviderName
from llm_gateway.storage.memory import InMemoryTenantRepository, InMemoryUsageRepository
from llm_gateway.storage.repositories import Tenant, TenantLimitPatch, UsageRecord

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _tenant(**overrides: object) -> Tenant:
    values: dict[str, object] = {
        "id": uuid4(),
        "name": "tenant-1",
        "created_at": BASE,
    }
    values.update(overrides)
    return Tenant(**values)  # pyright: ignore[reportArgumentType]


def _record(
    *,
    tenant_id: UUID,
    created_at: datetime,
    total_tokens: int = 10,
) -> UsageRecord:
    return UsageRecord(
        id=uuid4(),
        request_id=f"req-{uuid4()}",
        tenant_id=tenant_id,
        api_key_id=uuid4(),
        model_id="model-1",
        provider=ProviderName.FAKE,
        prompt_tokens=total_tokens,
        completion_tokens=0,
        total_tokens=total_tokens,
        cached_tokens=0,
        created_at=created_at,
    )


@pytest.mark.parametrize("field", ["monthly_token_quota", "requests_per_minute"])
@pytest.mark.parametrize("value", [0, -1])
def test_tenant_rejects_non_positive_limits(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=field):
        _tenant(**{field: value})


@pytest.mark.parametrize("field", ["monthly_token_quota", "requests_per_minute"])
def test_tenant_rejects_boolean_limits(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        _tenant(**{field: True})


@pytest.mark.parametrize("field", ["monthly_token_quota", "requests_per_minute"])
def test_tenant_allows_none_limits(field: str) -> None:
    tenant = _tenant(**{field: None})

    assert getattr(tenant, field) is None


async def test_memory_set_tenant_limits_sets_replaces_and_clears() -> None:
    repository = InMemoryTenantRepository()
    tenant = _tenant()
    await repository.create_tenant(tenant)

    updated = await repository.set_tenant_limits(
        tenant.id,
        patch=TenantLimitPatch(
            monthly_token_quota=100,
            requests_per_minute=5,
            set_monthly_token_quota=True,
            set_requests_per_minute=True,
        ),
    )
    assert updated is not None
    assert updated.monthly_token_quota == 100
    assert updated.requests_per_minute == 5
    assert await repository.get_tenant(tenant.id) == updated

    partial = await repository.set_tenant_limits(
        tenant.id,
        patch=TenantLimitPatch(
            monthly_token_quota=200,
            set_monthly_token_quota=True,
        ),
    )
    assert partial is not None
    assert partial.monthly_token_quota == 200
    assert partial.requests_per_minute == 5

    cleared = await repository.set_tenant_limits(
        tenant.id,
        patch=TenantLimitPatch(
            set_monthly_token_quota=True,
            set_requests_per_minute=True,
        ),
    )
    assert cleared is not None
    assert cleared.monthly_token_quota is None
    assert cleared.requests_per_minute is None


async def test_memory_set_tenant_limits_returns_none_for_unknown_tenant() -> None:
    repository = InMemoryTenantRepository()

    result = await repository.set_tenant_limits(
        uuid4(),
        patch=TenantLimitPatch(
            monthly_token_quota=1,
            requests_per_minute=1,
            set_monthly_token_quota=True,
            set_requests_per_minute=True,
        ),
    )

    assert result is None


async def test_memory_token_total_filters_tenant_and_half_open_window() -> None:
    repository = InMemoryUsageRepository()
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    await repository.record(_record(tenant_id=tenant_id, created_at=BASE, total_tokens=10))
    await repository.record(
        _record(tenant_id=tenant_id, created_at=BASE + timedelta(minutes=1), total_tokens=20)
    )
    await repository.record(
        _record(tenant_id=tenant_id, created_at=BASE + timedelta(minutes=2), total_tokens=40)
    )
    await repository.record(_record(tenant_id=other_tenant_id, created_at=BASE, total_tokens=100))

    assert (
        await repository.token_total(
            tenant_id=tenant_id,
            since=BASE,
            until=BASE + timedelta(minutes=3),
        )
        == 70
    )
    assert (
        await repository.token_total(
            tenant_id=tenant_id,
            since=BASE + timedelta(minutes=1),
            until=BASE + timedelta(minutes=3),
        )
        == 60
    )
    assert (
        await repository.token_total(
            tenant_id=tenant_id,
            since=BASE,
            until=BASE + timedelta(minutes=1),
        )
        == 10
    )


async def test_memory_token_total_rejects_invalid_windows() -> None:
    repository = InMemoryUsageRepository()

    with pytest.raises(ValueError, match="since must be before until"):
        await repository.token_total(
            tenant_id=uuid4(),
            since=BASE,
            until=BASE,
        )
    with pytest.raises(ValueError, match="since must be timezone-aware"):
        await repository.token_total(
            tenant_id=uuid4(),
            since=datetime(2026, 1, 1, 12, 0),  # noqa: DTZ001 - naive under test
            until=BASE,
        )


async def test_memory_set_tenant_limits_without_flags_is_a_noop() -> None:
    repository = InMemoryTenantRepository()
    tenant = _tenant(monthly_token_quota=100, requests_per_minute=5)
    await repository.create_tenant(tenant)

    result = await repository.set_tenant_limits(
        tenant.id,
        patch=TenantLimitPatch(),
    )

    assert result == tenant
    assert await repository.get_tenant(tenant.id) == tenant


async def test_memory_set_tenant_limits_toggles_audit_flag() -> None:
    repository = InMemoryTenantRepository()
    tenant = _tenant()
    await repository.create_tenant(tenant)

    enabled = await repository.set_tenant_limits(
        tenant.id,
        patch=TenantLimitPatch(audit_enabled=True, set_audit_enabled=True),
    )
    assert enabled is not None
    assert enabled.audit_enabled is True

    unchanged = await repository.set_tenant_limits(
        tenant.id,
        patch=TenantLimitPatch(monthly_token_quota=10, set_monthly_token_quota=True),
    )
    assert unchanged is not None
    assert unchanged.audit_enabled is True

    disabled = await repository.set_tenant_limits(
        tenant.id,
        patch=TenantLimitPatch(audit_enabled=False, set_audit_enabled=True),
    )
    assert disabled is not None
    assert disabled.audit_enabled is False
