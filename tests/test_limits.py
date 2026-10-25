from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from llm_gateway.auth.dependencies import AuthenticatedKey
from llm_gateway.auth.keys import hash_api_key
from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.services.limits import enforce_inference_limits, month_window
from llm_gateway.storage.rate_limits import RateLimitResult
from llm_gateway.storage.repositories import (
    ApiKeyRecord,
    Tenant,
    TenantLimitPatch,
)
from support import CapturingUsageRepository

NOW = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)


class MissingTenantRepository:
    async def create_tenant(self, tenant: Tenant) -> Tenant:
        raise NotImplementedError

    async def get_tenant(self, tenant_id: UUID) -> Tenant | None:
        return None

    async def list_tenants(self, *, limit: int, offset: int) -> tuple[Sequence[Tenant], int]:
        return [], 0

    async def set_tenant_limits(self, tenant_id: UUID, *, patch: TenantLimitPatch) -> Tenant | None:
        return None


class SpyRateLimiter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def hit(self, *, tenant_id: UUID, limit: int, now: datetime) -> RateLimitResult:
        self.calls.append({"tenant_id": tenant_id, "limit": limit, "now": now})
        return RateLimitResult(allowed=True, remaining=limit, retry_after_seconds=0)


def test_month_window_december_rolls_into_next_year() -> None:
    start, end = month_window(NOW)

    assert start == datetime(2026, 12, 1, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_month_window_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        month_window(datetime(2026, 12, 31, 23, 59, 59))  # noqa: DTZ001 - naive under test


async def test_missing_tenant_is_a_403_without_touching_limits(
    settings: Settings,
    make_container: Any,
) -> None:
    usage = CapturingUsageRepository()
    rate_limiter = SpyRateLimiter()
    container: Container = make_container(
        settings,
        usage=usage,
        rate_limiter=rate_limiter,
    )
    container.tenants = MissingTenantRepository()
    record = ApiKeyRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        name="key",
        key_hash=hash_api_key("secret"),
        key_prefix="sk-gw-000001",
        created_at=NOW,
    )

    with pytest.raises(ApiError) as info:
        await enforce_inference_limits(
            AuthenticatedKey(record=record),
            container,
        )

    assert info.value.status_code == 403
    assert info.value.code is ApiErrorCode.PERMISSION_DENIED
    assert info.value.error_type == "permission_error"
    assert info.value.message == "Tenant is not available"
    assert rate_limiter.calls == []
    assert usage.records == []
