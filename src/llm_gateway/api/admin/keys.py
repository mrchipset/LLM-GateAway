from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Response

from llm_gateway.auth.admin_auth import AdminPrincipal
from llm_gateway.auth.admin_deps import current_admin, require_write_access
from llm_gateway.auth.keys import generate_api_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.admin import (
    ApiKeyListResponse,
    ApiKeySummary,
    CreateApiKeyRequest,
    CreatedApiKeyResponse,
)
from llm_gateway.services.admin_audit import (
    key_snapshot,
    record_admin_event_safely,
)
from llm_gateway.storage.repositories import UnknownTenantError

router = APIRouter()

PaginationLimit = Annotated[int, Query(ge=1, le=100)]
PaginationOffset = Annotated[int, Query(ge=0)]


def _tenant_not_found(tenant_id: UUID) -> ApiError:
    return ApiError(
        status_code=404,
        code=ApiErrorCode.TENANT_NOT_FOUND,
        message=f"Tenant '{tenant_id}' was not found",
        error_type="invalid_request_error",
        param="tenant_id",
    )


@router.post("/keys", response_model=CreatedApiKeyResponse, status_code=201)
async def create_api_key(
    payload: CreateApiKeyRequest,
    principal: Annotated[AdminPrincipal, Depends(require_write_access)],
    container: Annotated[Container, Depends(get_container)],
) -> CreatedApiKeyResponse:
    now = container.clock.now()
    if payload.expires_at is not None and payload.expires_at <= now:
        raise ApiError.invalid_request(
            "expires_at must be in the future",
            param="expires_at",
        )

    tenant = await container.tenants.get_tenant(payload.tenant_id)
    if tenant is None:
        raise _tenant_not_found(payload.tenant_id)

    secret, record = generate_api_key(
        key_id=uuid4(),
        tenant_id=payload.tenant_id,
        name=payload.name,
        now=now,
        expires_at=payload.expires_at,
        requests_per_minute=payload.requests_per_minute,
        tokens_per_minute=payload.tokens_per_minute,
        max_concurrent_requests=payload.max_concurrent_requests,
    )
    try:
        await container.api_keys.create_key(record)
    except UnknownTenantError as exc:
        # The tenant can disappear between validation and the insert.
        raise _tenant_not_found(payload.tenant_id) from exc

    await record_admin_event_safely(
        container=container,
        principal=principal,
        action="api_key.created",
        target_type="api_key",
        target_id=str(record.id),
        after=key_snapshot(record),
    )

    # The plaintext secret is returned exactly once and never logged or stored.
    return CreatedApiKeyResponse(
        id=record.id,
        tenant_id=record.tenant_id,
        name=record.name,
        key=secret,
        key_prefix=record.key_prefix,
        created_at=record.created_at,
        expires_at=record.expires_at,
        requests_per_minute=record.requests_per_minute,
        tokens_per_minute=record.tokens_per_minute,
        max_concurrent_requests=record.max_concurrent_requests,
    )


@router.get("/keys", response_model=ApiKeyListResponse)
async def list_api_keys(
    _: Annotated[AdminPrincipal, Depends(current_admin)],
    container: Annotated[Container, Depends(get_container)],
    tenant_id: UUID | None = None,
    limit: PaginationLimit = 50,
    offset: PaginationOffset = 0,
) -> ApiKeyListResponse:
    if tenant_id is not None and await container.tenants.get_tenant(tenant_id) is None:
        raise _tenant_not_found(tenant_id)

    records, total = await container.api_keys.list_keys(
        limit=limit, offset=offset, tenant_id=tenant_id
    )
    return ApiKeyListResponse(
        items=[
            ApiKeySummary(
                id=record.id,
                tenant_id=record.tenant_id,
                name=record.name,
                key_prefix=record.key_prefix,
                created_at=record.created_at,
                expires_at=record.expires_at,
                revoked_at=record.revoked_at,
                last_used_at=record.last_used_at,
                requests_per_minute=record.requests_per_minute,
                tokens_per_minute=record.tokens_per_minute,
                max_concurrent_requests=record.max_concurrent_requests,
            )
            for record in records
        ],
        total=total,
        limit=limit,
        offset=offset,
        tenant_id=tenant_id,
    )


@router.delete("/keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: UUID,
    principal: Annotated[AdminPrincipal, Depends(require_write_access)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    existing = await container.api_keys.get_key(key_id)
    revoked = await container.api_keys.revoke_key(key_id, container.clock.now())
    if not revoked:
        raise ApiError(
            status_code=404,
            code=ApiErrorCode.KEY_NOT_FOUND,
            message="API key not found or already revoked",
            error_type="invalid_request_error",
        )

    if existing is not None:
        before = key_snapshot(existing)
        await record_admin_event_safely(
            container=container,
            principal=principal,
            action="api_key.revoked",
            target_type="api_key",
            target_id=str(key_id),
            before=before,
            after={**before, "revoked": True},
        )
    return Response(status_code=204)
