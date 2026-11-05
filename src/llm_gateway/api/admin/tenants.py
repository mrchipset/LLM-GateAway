from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Response

from llm_gateway.auth.admin_auth import AdminPrincipal
from llm_gateway.auth.admin_deps import current_admin, require_owner, require_write_access
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.admin import (
    CreateTenantRequest,
    ModelAccessResponse,
    TenantBillingResponse,
    TenantDetail,
    TenantListResponse,
    UpdateModelAccessRequest,
    UpdateTenantLimitsRequest,
)
from llm_gateway.services.admin_audit import (
    record_admin_event_safely,
    tenant_snapshot,
)
from llm_gateway.services.billing import budget_remaining, month_window
from llm_gateway.storage.repositories import (
    DuplicateTenantError,
    ModelAccessMode,
    Tenant,
    TenantLimitPatch,
)

router = APIRouter()

PaginationLimit = Annotated[int, Query(ge=1, le=100)]
PaginationOffset = Annotated[int, Query(ge=0)]


def _detail(tenant: Tenant) -> TenantDetail:
    return TenantDetail(
        id=tenant.id,
        name=tenant.name,
        created_at=tenant.created_at,
        monthly_token_quota=tenant.monthly_token_quota,
        requests_per_minute=tenant.requests_per_minute,
        tokens_per_minute=tenant.tokens_per_minute,
        max_concurrent_requests=tenant.max_concurrent_requests,
        audit_enabled=tenant.audit_enabled,
        model_access_mode=tenant.model_access_mode,
        plan_tokens=tenant.plan_tokens,
        plan_allow_overage=tenant.plan_allow_overage,
        monthly_cost_budget=tenant.monthly_cost_budget,
        audit_retention_days=tenant.audit_retention_days,
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
    principal: Annotated[AdminPrincipal, Depends(require_write_access)],
    container: Annotated[Container, Depends(get_container)],
) -> TenantDetail:
    tenant = Tenant(
        id=uuid4(),
        name=payload.name,
        created_at=container.clock.now(),
        monthly_token_quota=payload.monthly_token_quota,
        requests_per_minute=payload.requests_per_minute,
        tokens_per_minute=payload.tokens_per_minute,
        max_concurrent_requests=payload.max_concurrent_requests,
        audit_enabled=payload.audit_enabled,
        audit_retention_days=payload.audit_retention_days,
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

    await record_admin_event_safely(
        container=container,
        principal=principal,
        action="tenant.created",
        target_type="tenant",
        target_id=str(created.id),
        after=tenant_snapshot(created),
    )
    return _detail(created)


@router.patch("/tenants/{tenant_id}", response_model=TenantDetail)
async def update_tenant_limits(
    tenant_id: UUID,
    payload: UpdateTenantLimitsRequest,
    principal: Annotated[AdminPrincipal, Depends(require_write_access)],
    container: Annotated[Container, Depends(get_container)],
) -> TenantDetail:
    provided = payload.model_fields_set
    patch = TenantLimitPatch(
        monthly_token_quota=payload.monthly_token_quota,
        requests_per_minute=payload.requests_per_minute,
        tokens_per_minute=payload.tokens_per_minute,
        max_concurrent_requests=payload.max_concurrent_requests,
        audit_enabled=payload.audit_enabled,
        plan_tokens=payload.plan_tokens,
        plan_allow_overage=payload.plan_allow_overage,
        monthly_cost_budget=payload.monthly_cost_budget,
        audit_retention_days=payload.audit_retention_days,
        set_monthly_token_quota="monthly_token_quota" in provided,
        set_requests_per_minute="requests_per_minute" in provided,
        set_tokens_per_minute="tokens_per_minute" in provided,
        set_max_concurrent_requests="max_concurrent_requests" in provided,
        set_audit_enabled=payload.audit_enabled is not None,
        set_plan_tokens="plan_tokens" in provided,
        set_plan_allow_overage=payload.plan_allow_overage is not None,
        set_monthly_cost_budget="monthly_cost_budget" in provided,
        set_audit_retention_days="audit_retention_days" in provided,
    )
    existing = await container.tenants.get_tenant(tenant_id)
    if existing is None:
        raise _not_found(tenant_id)

    if "name" in provided and payload.name is not None:
        try:
            renamed = await container.tenants.rename_tenant(tenant_id, name=payload.name)
        except DuplicateTenantError as exc:
            raise ApiError(
                status_code=409,
                code=ApiErrorCode.DUPLICATE_TENANT,
                message=f"Tenant '{payload.name}' already exists",
                error_type="invalid_request_error",
                param="name",
            ) from exc
        if renamed is None:
            raise _not_found(tenant_id)

    updated = await container.tenants.set_tenant_limits(tenant_id, patch=patch)
    if updated is None:
        raise _not_found(tenant_id)

    await record_admin_event_safely(
        container=container,
        principal=principal,
        action="tenant.updated",
        target_type="tenant",
        target_id=str(tenant_id),
        before=tenant_snapshot(existing),
        after=tenant_snapshot(updated),
    )
    return _detail(updated)


@router.delete("/tenants/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: UUID,
    principal: Annotated[AdminPrincipal, Depends(require_owner)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    existing = await container.tenants.get_tenant(tenant_id)
    if existing is None:
        raise _not_found(tenant_id)

    now = container.clock.now()
    deleted = await container.tenants.soft_delete_tenant(tenant_id, deleted_at=now)
    if deleted is None:
        raise _not_found(tenant_id)
    await container.api_keys.revoke_keys_for_tenant(tenant_id, now)

    await record_admin_event_safely(
        container=container,
        principal=principal,
        action="tenant.deleted",
        target_type="tenant",
        target_id=str(tenant_id),
        before=tenant_snapshot(existing),
        after={"deleted_at": now.isoformat()},
    )
    return Response(status_code=204)


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants(
    _: Annotated[AdminPrincipal, Depends(current_admin)],
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


@router.get("/tenants/{tenant_id}/billing", response_model=TenantBillingResponse)
async def tenant_billing(
    tenant_id: UUID,
    _: Annotated[AdminPrincipal, Depends(current_admin)],
    container: Annotated[Container, Depends(get_container)],
) -> TenantBillingResponse:
    tenant = await container.tenants.get_tenant(tenant_id)
    if tenant is None:
        raise _not_found(tenant_id)

    period_start, period_end = month_window(container.clock.now())
    usage = await container.usage.monthly_totals(
        tenant_id=tenant_id,
        since=period_start,
        until=period_end,
    )
    return TenantBillingResponse(
        tenant_id=tenant.id,
        currency=container.settings.billing_currency,
        enabled=container.settings.billing_enabled,
        period_start=period_start,
        period_end=period_end,
        plan_tokens=tenant.plan_tokens,
        plan_allow_overage=tenant.plan_allow_overage,
        monthly_cost_budget=tenant.monthly_cost_budget,
        used_tokens=usage.total_tokens,
        covered_tokens=usage.covered_tokens,
        billable_tokens=usage.billable_tokens,
        requests=usage.requests,
        list_cost=usage.list_cost,
        billed_cost=usage.billed_cost,
        budget_remaining=budget_remaining(tenant, usage),
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
    _: Annotated[AdminPrincipal, Depends(current_admin)],
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
    principal: Annotated[AdminPrincipal, Depends(require_write_access)],
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

    before = await container.tenants.get_model_access(tenant_id)
    access = await container.tenants.set_model_access(
        tenant_id,
        mode=payload.mode,
        model_ids=model_ids,
    )
    if access is None:
        raise _not_found(tenant_id)

    await record_admin_event_safely(
        container=container,
        principal=principal,
        action="tenant.model_access.updated",
        target_type="tenant",
        target_id=str(tenant_id),
        before=(
            {"mode": str(before.mode), "model_ids": list(before.model_ids)}
            if before is not None
            else None
        ),
        after={"mode": str(access.mode), "model_ids": list(access.model_ids)},
    )
    return _model_access_response(tenant_id, access.mode, access.model_ids)
