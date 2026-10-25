from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query

from llm_gateway.auth.dependencies import require_master_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.admin import (
    CreateTenantRequest,
    TenantDetail,
    TenantListResponse,
)
from llm_gateway.storage.repositories import DuplicateTenantError, Tenant

router = APIRouter(dependencies=[Depends(require_master_key)])

PaginationLimit = Annotated[int, Query(ge=1, le=100)]
PaginationOffset = Annotated[int, Query(ge=0)]


def _detail(tenant: Tenant) -> TenantDetail:
    return TenantDetail(id=tenant.id, name=tenant.name, created_at=tenant.created_at)


@router.post("/tenants", response_model=TenantDetail, status_code=201)
async def create_tenant(
    payload: CreateTenantRequest,
    container: Annotated[Container, Depends(get_container)],
) -> TenantDetail:
    tenant = Tenant(id=uuid4(), name=payload.name, created_at=container.clock.now())
    try:
        created = await container.tenants.create_tenant(tenant)
    except DuplicateTenantError as exc:
        raise ApiError(
            status_code=409,
            code=ApiErrorCode.DUPLICATE_TENANT,
            message=f"Tenant '{payload.name}' already exists",
            error_type="invalid_request_error",
            param="name",
        ) from exc
    return _detail(created)


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants(
    container: Annotated[Container, Depends(get_container)],
    limit: PaginationLimit = 50,
    offset: PaginationOffset = 0,
) -> TenantListResponse:
    tenants, total = await container.tenants.list_tenants(limit=limit, offset=offset)
    return TenantListResponse(
        items=[_detail(tenant) for tenant in tenants],
        total=total,
        limit=limit,
        offset=offset,
    )
