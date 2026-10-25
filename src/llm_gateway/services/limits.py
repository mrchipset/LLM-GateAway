from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends

from llm_gateway.auth.dependencies import AuthenticatedKey, require_api_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.logging import get_logger

logger = get_logger(__name__)


def month_window(now: datetime) -> tuple[datetime, datetime]:
    """Return the half-open UTC calendar-month window containing ``now``."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    month_start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)
    return month_start, next_month_start


async def enforce_inference_limits(
    api_key: Annotated[AuthenticatedKey, Depends(require_api_key)],
    container: Annotated[Container, Depends(get_container)],
) -> AuthenticatedKey:
    tenant = await container.tenants.get_tenant(api_key.record.tenant_id)
    if tenant is None:
        raise ApiError(
            status_code=403,
            code=ApiErrorCode.PERMISSION_DENIED,
            message="Tenant is not available",
            error_type="permission_error",
        )

    now = container.clock.now()

    if tenant.monthly_token_quota is not None:
        month_start, next_month_start = month_window(now)
        used = await container.usage.token_total(
            tenant_id=tenant.id,
            since=month_start,
            until=next_month_start,
        )
        if used >= tenant.monthly_token_quota:
            logger.warning(
                "tenant_quota_exceeded",
                extra={
                    "tenant_id": str(tenant.id),
                    "quota": tenant.monthly_token_quota,
                    "used": used,
                },
            )
            raise ApiError(
                status_code=429,
                code=ApiErrorCode.TENANT_QUOTA_EXCEEDED,
                message="Tenant monthly token quota exceeded",
                error_type="insufficient_quota",
            )

    if tenant.requests_per_minute is not None:
        limit_result = await container.rate_limiter.hit(
            tenant_id=tenant.id,
            limit=tenant.requests_per_minute,
            now=now,
        )
        if not limit_result.allowed:
            retry_after = max(1, math.ceil(limit_result.retry_after_seconds))
            logger.warning(
                "tenant_rate_limited",
                extra={
                    "tenant_id": str(tenant.id),
                    "limit": tenant.requests_per_minute,
                    "retry_after": retry_after,
                },
            )
            raise ApiError(
                status_code=429,
                code=ApiErrorCode.RATE_LIMITED,
                message="Tenant request rate limit exceeded",
                error_type="rate_limit_error",
                headers={"Retry-After": str(retry_after)},
            )

    return api_key
