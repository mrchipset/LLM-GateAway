from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query

from llm_gateway.auth.dependencies import require_master_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.admin import (
    CreateTenantRequest,
    ModelAccessResponse,
    TenantDetail,
    TenantListResponse,
    UpdateModelAccessRequest,
    UpdateTenantLimitsRequest,
)
from llm_gateway.storage.repositories import (
    DuplicateTenantError,
    ModelAccessMode,
    Tenant,
    TenantLimitPatch,
)

router = APIRouter(dependencies=[Depends(require_master_key)])

PaginationLimit = Annotated[int, Query(ge=1, le=100)]
PaginationOffset = Annotated[int, Query(ge=0)]


def _detail(tenant: Tenant) -> TenantDetail:
    return TenantDetail(
        id=tenant.id,
        name=tenant.name,
        created_at=tenant.created_at,
        monthly_token_quota=tenant.monthly_token_quota,
        requests_per_minute=tenant.requests_per_minute,
        audit_enabled=tenant.audit_enabled,
        model_access_mode=tenant.model_access_mode,
    )


def _not_found(tenant_id: UUID) -> ApiError:
    return ApiError(
        status_code=404,
        code=ApiErrorCode.TENANT_NOT_FOUND,
        message=f"Tenant '{tenant_id}' was not found",
        error_type="invalid_request_error",
        param="tenant_id",
    )


@router.post("/tenants", response_model=TenantDetail, status_code=201)
async def create_tenant(
    payload: CreateTenantRequest,
    container: Annotated[Container, Depends(get_container)],
) -> TenantDetail:
    tenant = Tenant(
        id=uuid4(),
        name=payload.name,
        created_at=container.clock.now(),
        monthly_token_quota=payload.monthly_token_quota,
        requests_per_minute=payload.requests_per_minute,
        audit_enabled=payload.audit_enabled,
    )
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


@router.patch("/tenants/{tenant_id}", response_model=TenantDetail)
async def update_tenant_limits(
    tenant_id: UUID,
    payload: UpdateTenantLimitsRequest,
    container: Annotated[Container, Depends(get_container)],
) -> TenantDetail:
    provided = payload.model_fields_set
    patch = TenantLimitPatch(
        monthly_token_quota=payload.monthly_token_quota,
        requests_per_minute=payload.requests_per_minute,
        audit_enabled=payload.audit_enabled,
        set_monthly_token_quota="monthly_token_quota" in provided,
        set_requests_per_minute="requests_per_minute" in provided,
        set_audit_enabled=payload.audit_enabled is not None,
    )
    updated = await container.tenants.set_tenant_limits(tenant_id, patch=patch)
    if updated is None:
        raise _not_found(tenant_id)
    return _detail(updated)


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


def _model_access_response(
    tenant_id: UUID,
    mode: ModelAccessMode,
    model_ids: tuple[str, ...],
) -> ModelAccessResponse:
    return ModelAccessResponse(
        tenant_id=tenant_id,
        mode=mode,
        model_ids=list(model_ids),
    )


@router.get(
    "/tenants/{tenant_id}/model-access",
    response_model=ModelAccessResponse,
)
async def get_tenant_model_access(
    tenant_id: UUID,
    container: Annotated[Container, Depends(get_container)],
) -> ModelAccessResponse:
    access = await container.tenants.get_model_access(tenant_id)
    if access is None:
        raise _not_found(tenant_id)
    return _model_access_response(tenant_id, access.mode, access.model_ids)


@router.put(
    "/tenants/{tenant_id}/model-access",
    response_model=ModelAccessResponse,
)
async def replace_tenant_model_access(
    tenant_id: UUID,
    payload: UpdateModelAccessRequest,
    container: Annotated[Container, Depends(get_container)],
) -> ModelAccessResponse:
    tenant = await container.tenants.get_tenant(tenant_id)
    if tenant is None:
        raise _not_found(tenant_id)

    model_ids = (
        tuple(sorted(set(payload.model_ids))) if payload.mode is ModelAccessMode.ALLOWLIST else ()
    )
    for model_id in model_ids:
        if await container.models.get_model(model_id) is None:
            raise ApiError(
                status_code=404,
                code=ApiErrorCode.MODEL_NOT_FOUND,
                message=f"Model '{model_id}' was not found",
                error_type="invalid_request_error",
                param="model_ids",
            )

    access = await container.tenants.set_model_access(
        tenant_id,
        mode=payload.mode,
        model_ids=model_ids,
    )
    if access is None:
        raise _not_found(tenant_id)
    return _model_access_response(tenant_id, access.mode, access.model_ids)
