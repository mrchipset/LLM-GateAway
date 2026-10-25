from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from llm_gateway.auth.dependencies import require_master_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.usage import (
    KeyUsageResponse,
    KeyUsageSummary,
    UsageModelSummary,
    UsagePointSummary,
    UsageSeriesResponse,
    UsageSummaryResponse,
)
from llm_gateway.storage.repositories import TimeBucket

router = APIRouter(dependencies=[Depends(require_master_key)])

DEFAULT_SERIES_SPAN = timedelta(days=30)
MAX_SERIES_POINTS = 1000


def _require_aware(value: datetime, param: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiError.invalid_request(
            f"{param} must be timezone-aware",
            param=param,
        )


def _validate_window(since: datetime | None, until: datetime | None) -> None:
    if since is not None:
        _require_aware(since, "since")
    if until is not None:
        _require_aware(until, "until")
    if since is not None and until is not None and since >= until:
        raise ApiError.invalid_request(
            "since must be before until",
            param="since",
        )


async def _ensure_tenant(container: Container, tenant_id: UUID | None) -> None:
    if tenant_id is None:
        return
    tenant = await container.tenants.get_tenant(tenant_id)
    if tenant is None:
        raise ApiError(
            status_code=404,
            code=ApiErrorCode.TENANT_NOT_FOUND,
            message=f"Tenant '{tenant_id}' was not found",
            error_type="invalid_request_error",
            param="tenant_id",
        )


def _bucket_step(bucket: TimeBucket) -> timedelta:
    if bucket is TimeBucket.HOUR:
        return timedelta(hours=1)
    return timedelta(days=1)


def _floor_bucket(value: datetime, bucket: TimeBucket) -> datetime:
    utc = value.astimezone(UTC)
    if bucket is TimeBucket.HOUR:
        return utc.replace(minute=0, second=0, microsecond=0)
    return utc.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/usage/summary", response_model=UsageSummaryResponse)
async def usage_summary(
    container: Annotated[Container, Depends(get_container)],
    tenant_id: UUID | None = None,
    model_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> UsageSummaryResponse:
    _validate_window(since, until)
    await _ensure_tenant(container, tenant_id)

    by_model = await container.usage.summary_by_model(
        tenant_id=tenant_id,
        model_id=model_id,
        since=since,
        until=until,
    )
    return UsageSummaryResponse(
        prompt_tokens=sum(item.prompt_tokens for item in by_model),
        completion_tokens=sum(item.completion_tokens for item in by_model),
        cached_tokens=sum(item.cached_tokens for item in by_model),
        total_tokens=sum(item.total_tokens for item in by_model),
        requests=sum(item.requests for item in by_model),
        by_model=[
            UsageModelSummary(
                model_id=item.model_id,
                provider=item.provider,
                prompt_tokens=item.prompt_tokens,
                completion_tokens=item.completion_tokens,
                cached_tokens=item.cached_tokens,
                total_tokens=item.total_tokens,
                requests=item.requests,
            )
            for item in by_model
        ],
    )


@router.get("/usage/by-key", response_model=KeyUsageResponse)
async def usage_by_key(
    container: Annotated[Container, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    tenant_id: UUID | None = None,
    model_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> KeyUsageResponse:
    _validate_window(since, until)
    await _ensure_tenant(container, tenant_id)

    by_key = await container.usage.summary_by_key(
        tenant_id=tenant_id,
        model_id=model_id,
        since=since,
        until=until,
    )
    by_key = by_key[:limit]
    records = await container.api_keys.get_keys([item.api_key_id for item in by_key])
    keys_by_id = {record.id: record for record in records}
    return KeyUsageResponse(
        items=[
            KeyUsageSummary(
                api_key_id=item.api_key_id,
                name=keys_by_id[item.api_key_id].name if item.api_key_id in keys_by_id else None,
                key_prefix=keys_by_id[item.api_key_id].key_prefix
                if item.api_key_id in keys_by_id
                else None,
                prompt_tokens=item.prompt_tokens,
                completion_tokens=item.completion_tokens,
                cached_tokens=item.cached_tokens,
                total_tokens=item.total_tokens,
                requests=item.requests,
            )
            for item in by_key
        ],
        limit=limit,
    )


@router.get("/usage/series", response_model=UsageSeriesResponse)
async def usage_series(
    container: Annotated[Container, Depends(get_container)],
    bucket: TimeBucket = TimeBucket.DAY,
    tenant_id: UUID | None = None,
    model_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> UsageSeriesResponse:
    if since is not None:
        _require_aware(since, "since")
    if until is not None:
        _require_aware(until, "until")
    now = container.clock.now()
    resolved_until = until if until is not None else now
    resolved_since = since if since is not None else resolved_until - DEFAULT_SERIES_SPAN
    _validate_window(resolved_since, resolved_until)

    step = _bucket_step(bucket)
    first_bucket = _floor_bucket(resolved_since, bucket)
    point_count = math.ceil((resolved_until - first_bucket).total_seconds() / step.total_seconds())
    if point_count > MAX_SERIES_POINTS:
        raise ApiError.invalid_request(
            "usage series window is too large; widen the bucket or narrow the window",
            param="since",
        )

    await _ensure_tenant(container, tenant_id)

    sparse_points = await container.usage.summary_series(
        tenant_id=tenant_id,
        model_id=model_id,
        since=resolved_since,
        until=resolved_until,
        bucket=bucket,
    )
    points_by_start = {point.bucket_start: point for point in sparse_points}
    points: list[UsagePointSummary] = []
    for index in range(point_count):
        bucket_start = first_bucket + step * index
        point = points_by_start.get(bucket_start)
        points.append(
            UsagePointSummary(
                bucket_start=bucket_start,
                prompt_tokens=point.prompt_tokens if point is not None else 0,
                completion_tokens=(point.completion_tokens if point is not None else 0),
                cached_tokens=point.cached_tokens if point is not None else 0,
                total_tokens=point.total_tokens if point is not None else 0,
                requests=point.requests if point is not None else 0,
            )
        )
    return UsageSeriesResponse(bucket=bucket, points=points)
