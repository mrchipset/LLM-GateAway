from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from llm_gateway.auth.dependencies import require_master_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.usage import UsageModelSummary, UsageSummaryResponse

router = APIRouter(dependencies=[Depends(require_master_key)])


def _require_aware(value: datetime, param: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiError.invalid_request(
            f"{param} must be timezone-aware",
            param=param,
        )


@router.get("/usage/summary", response_model=UsageSummaryResponse)
async def usage_summary(
    container: Annotated[Container, Depends(get_container)],
    tenant_id: UUID | None = None,
    model_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> UsageSummaryResponse:
    if since is not None:
        _require_aware(since, "since")
    if until is not None:
        _require_aware(until, "until")
    if since is not None and until is not None and since >= until:
        raise ApiError.invalid_request(
            "since must be before until",
            param="since",
        )

    if tenant_id is not None:
        tenant = await container.tenants.get_tenant(tenant_id)
        if tenant is None:
            raise ApiError(
                status_code=404,
                code=ApiErrorCode.TENANT_NOT_FOUND,
                message=f"Tenant '{tenant_id}' was not found",
                error_type="invalid_request_error",
                param="tenant_id",
            )

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
