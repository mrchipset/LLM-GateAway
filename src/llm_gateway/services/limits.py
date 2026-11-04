from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from llm_gateway.auth.dependencies import AuthenticatedKey, require_api_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.logging import get_logger
from llm_gateway.metrics import current_metrics
from llm_gateway.services.billing import month_window
from llm_gateway.storage.repositories import Tenant

logger = get_logger(__name__)

__all__ = ["InferenceAccess", "enforce_inference_limits", "month_window"]


@dataclass(frozen=True, slots=True)
class InferenceAccess:
    """Everything the inference route needs after authentication and limits."""

    api_key: AuthenticatedKey
    tenant: Tenant


async def enforce_inference_limits(
    api_key: Annotated[AuthenticatedKey, Depends(require_api_key)],
    container: Annotated[Container, Depends(get_container)],
) -> InferenceAccess:
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
            current_metrics().rejections.add(1, {"reason": "tenant_quota"})
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
            current_metrics().rejections.add(1, {"reason": "rate_limit"})
            raise ApiError(
                status_code=429,
                code=ApiErrorCode.RATE_LIMITED,
                message="Tenant request rate limit exceeded",
                error_type="rate_limit_error",
                headers={"Retry-After": str(retry_after)},
            )

    return InferenceAccess(api_key=api_key, tenant=tenant)
