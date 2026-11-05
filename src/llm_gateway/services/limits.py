from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends

from llm_gateway.auth.dependencies import AuthenticatedKey, require_api_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.logging import get_logger
from llm_gateway.metrics import current_metrics
from llm_gateway.services.billing import month_window
from llm_gateway.storage.rate_limits import BucketScope, RateLimiterUnavailable
from llm_gateway.storage.repositories import ApiKeyRecord, Tenant

logger = get_logger(__name__)

__all__ = [
    "InferenceAccess",
    "acquire_concurrency",
    "enforce_inference_limits",
    "enforce_model_limits",
    "month_window",
    "release_concurrency",
]

_BUCKET_WINDOW_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class InferenceAccess:
    """Everything the inference route needs after authentication and limits."""

    api_key: AuthenticatedKey
    tenant: Tenant


def _bucket_key(identifier: str, dimension: str) -> str:
    return f"{identifier}:{dimension}"


def _deny_rate_limit(*, retry_after_seconds: float) -> ApiError:
    return ApiError(
        status_code=429,
        code=ApiErrorCode.RATE_LIMITED,
        message="Request rate limit exceeded",
        error_type="rate_limit_error",
        headers={"Retry-After": str(max(1, math.ceil(retry_after_seconds)))},
    )


def _deny_token_limit(*, retry_after_seconds: float) -> ApiError:
    return ApiError(
        status_code=429,
        code=ApiErrorCode.TOKEN_RATE_LIMITED,
        message="Token rate limit exceeded",
        error_type="rate_limit_error",
        headers={"Retry-After": str(max(1, math.ceil(retry_after_seconds)))},
    )


def _degraded(container: Container, exc: RateLimiterUnavailable, *, scope: str) -> None:
    current_metrics().rate_limit_degraded.add(1, {"reason": exc.reason})
    logger.warning(
        "rate_limit_unavailable",
        extra={
            "scope": scope,
            "reason": exc.reason,
            "fail_open": container.settings.rate_limit_fail_open,
        },
    )


async def _take(
    container: Container,
    *,
    scope: BucketScope,
    key: str,
    limit: int,
    now: datetime,
) -> None:
    result = await container.rate_limiter.take(scope=scope, key=key, limit=limit, now=now)
    if not result.allowed:
        logger.warning(
            "rate_limit_exceeded",
            extra={"scope": scope, "limit": limit, "reason": "request_rate"},
        )
        current_metrics().rejections.add(1, {"reason": "rate_limit"})
        raise _deny_rate_limit(retry_after_seconds=result.retry_after_seconds)


async def _check_tokens(
    container: Container,
    *,
    scope: BucketScope,
    key: str,
    limit: int,
    now: datetime,
) -> None:
    available = await container.rate_limiter.available(scope=scope, key=key, limit=limit, now=now)
    if available <= 0:
        retry_after = (1.0 - available) / (limit / _BUCKET_WINDOW_SECONDS)
        logger.warning(
            "rate_limit_exceeded",
            extra={"scope": scope, "limit": limit, "reason": "token_rate"},
        )
        current_metrics().rejections.add(1, {"reason": "token_rate_limit"})
        raise _deny_token_limit(retry_after_seconds=retry_after)


async def enforce_model_limits(
    container: Container,
    *,
    model_id: str,
    now: datetime,
) -> int | None:
    """Apply per-model RPM/TPM and return the model's token limit for settlement."""
    model = await container.models.get_model(model_id)
    if model is None:
        return None
    if model.requests_per_minute is None and model.tokens_per_minute is None:
        return model.tokens_per_minute
    try:
        if model.requests_per_minute is not None:
            await _take(
                container,
                scope="model",
                key=_bucket_key(model.id, "rpm"),
                limit=model.requests_per_minute,
                now=now,
            )
        if model.tokens_per_minute is not None:
            await _check_tokens(
                container,
                scope="model",
                key=_bucket_key(model.id, "tpm"),
                limit=model.tokens_per_minute,
                now=now,
            )
    except RateLimiterUnavailable as exc:
        _degraded(container, exc, scope="model")
        if not container.settings.rate_limit_fail_open:
            raise _limiter_unavailable() from exc
    return model.tokens_per_minute


def _limiter_unavailable() -> ApiError:
    return ApiError(
        status_code=503,
        code=ApiErrorCode.RATE_LIMITER_UNAVAILABLE,
        message="Rate limiter is unavailable",
        error_type="server_error",
        headers={"Retry-After": "1"},
    )


def _deny_concurrency() -> ApiError:
    return ApiError(
        status_code=429,
        code=ApiErrorCode.CONCURRENCY_LIMITED,
        message="Concurrent request limit exceeded",
        error_type="rate_limit_error",
        headers={"Retry-After": "1"},
    )


async def acquire_concurrency(
    container: Container,
    *,
    tenant: Tenant,
    key_record: ApiKeyRecord,
) -> list[tuple[BucketScope, str]]:
    """Take tenant and key in-flight slots; returns the leases that must be released."""
    limits: tuple[tuple[BucketScope, str, int | None], ...] = (
        ("tenant", f"{tenant.id}:conc", tenant.max_concurrent_requests),
        ("key", f"{key_record.id}:conc", key_record.max_concurrent_requests),
    )
    leases: list[tuple[BucketScope, str]] = []
    ttl = container.settings.concurrency_lease_seconds
    try:
        for scope, bucket, limit in limits:
            if limit is None:
                continue
            acquired = await container.rate_limiter.acquire(
                scope=scope,
                key=bucket,
                limit=limit,
                ttl_seconds=ttl,
            )
            if not acquired:
                await release_concurrency(container, leases)
                current_metrics().rejections.add(1, {"reason": "concurrency"})
                logger.warning(
                    "concurrency_limit_exceeded",
                    extra={"scope": scope, "limit": limit},
                )
                raise _deny_concurrency()
            leases.append((scope, bucket))
    except RateLimiterUnavailable as exc:
        _degraded(container, exc, scope="concurrency")
        await release_concurrency(container, leases)
        if not container.settings.rate_limit_fail_open:
            raise _limiter_unavailable() from exc
        return []
    return leases


async def release_concurrency(
    container: Container,
    leases: list[tuple[BucketScope, str]],
) -> None:
    for scope, bucket in leases:
        try:
            await container.rate_limiter.release(scope=scope, key=bucket)
        except RateLimiterUnavailable as exc:
            _degraded(container, exc, scope="concurrency")


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

    try:
        if tenant.requests_per_minute is not None:
            await _take(
                container,
                scope="tenant",
                key=_bucket_key(str(tenant.id), "rpm"),
                limit=tenant.requests_per_minute,
                now=now,
            )
        if api_key.record.requests_per_minute is not None:
            await _take(
                container,
                scope="key",
                key=_bucket_key(str(api_key.record.id), "rpm"),
                limit=api_key.record.requests_per_minute,
                now=now,
            )
        if tenant.tokens_per_minute is not None:
            await _check_tokens(
                container,
                scope="tenant",
                key=_bucket_key(str(tenant.id), "tpm"),
                limit=tenant.tokens_per_minute,
                now=now,
            )
        if api_key.record.tokens_per_minute is not None:
            await _check_tokens(
                container,
                scope="key",
                key=_bucket_key(str(api_key.record.id), "tpm"),
                limit=api_key.record.tokens_per_minute,
                now=now,
            )
    except RateLimiterUnavailable as exc:
        _degraded(container, exc, scope="inference")
        if not container.settings.rate_limit_fail_open:
            raise _limiter_unavailable() from exc

    return InferenceAccess(api_key=api_key, tenant=tenant)
