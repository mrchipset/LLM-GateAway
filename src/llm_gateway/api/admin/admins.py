from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query

from llm_gateway.auth.admin_auth import AdminPrincipal, normalize_username
from llm_gateway.auth.admin_deps import require_owner
from llm_gateway.auth.passwords import hash_password
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.admin import (
    AdminDetail,
    AdminListResponse,
    CreateAdminRequest,
    UpdateAdminRequest,
)
from llm_gateway.services.admin_audit import (
    admin_snapshot,
    record_admin_event_safely,
)
from llm_gateway.storage.repositories import (
    AdminUser,
    DuplicateAdminError,
    LastOwnerError,
)

router = APIRouter(prefix="/admins", tags=["admin-users"])

PaginationLimit = Annotated[int, Query(ge=1, le=100)]
PaginationOffset = Annotated[int, Query(ge=0)]


def _detail(admin: AdminUser) -> AdminDetail:
    return AdminDetail(
        id=admin.id,
        username=admin.username,
        display_name=admin.display_name,
        role=admin.role,
        active=admin.active,
        created_at=admin.created_at,
        updated_at=admin.updated_at,
        last_login_at=admin.last_login_at,
    )


def _not_found(admin_id: UUID) -> ApiError:
    return ApiError(
        status_code=404,
        code=ApiErrorCode.ADMIN_NOT_FOUND,
        message=f"Admin '{admin_id}' was not found",
        error_type="invalid_request_error",
    )


@router.get("", response_model=AdminListResponse)
async def list_admins(
    _: Annotated[AdminPrincipal, Depends(require_owner)],
    container: Annotated[Container, Depends(get_container)],
    limit: PaginationLimit = 50,
    offset: PaginationOffset = 0,
) -> AdminListResponse:
    admins, total = await container.admins.list_admins(limit=limit, offset=offset)
    return AdminListResponse(
        items=[_detail(admin) for admin in admins],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=AdminDetail, status_code=201)
async def create_admin(
    payload: CreateAdminRequest,
    principal: Annotated[AdminPrincipal, Depends(require_owner)],
    container: Annotated[Container, Depends(get_container)],
) -> AdminDetail:
    now = container.clock.now()
    admin = AdminUser(
        id=uuid4(),
        username=normalize_username(payload.username),
        display_name=payload.display_name.strip(),
        role=payload.role,
        password_hash=hash_password(payload.password),
        active=True,
        created_at=now,
        updated_at=now,
        password_changed_at=now,
    )
    try:
        created = await container.admins.create_admin(admin)
    except DuplicateAdminError as exc:
        raise ApiError(
            status_code=409,
            code=ApiErrorCode.DUPLICATE_ADMIN,
            message=f"Admin '{admin.username}' already exists",
            error_type="invalid_request_error",
            param="username",
        ) from exc

    await record_admin_event_safely(
        container=container,
        principal=principal,
        action="admin.created",
        target_type="admin",
        target_id=str(created.id),
        after=admin_snapshot(created),
    )
    return _detail(created)


@router.patch("/{admin_id}", response_model=AdminDetail)
async def update_admin(
    admin_id: UUID,
    payload: UpdateAdminRequest,
    principal: Annotated[AdminPrincipal, Depends(require_owner)],
    container: Annotated[Container, Depends(get_container)],
) -> AdminDetail:
    existing = await container.admins.get_admin(admin_id)
    if existing is None:
        raise _not_found(admin_id)

    now = container.clock.now()
    password_changed = payload.password is not None
    try:
        updated = await container.admins.update_admin(
            admin_id,
            role=payload.role,
            active=payload.active,
            display_name=payload.display_name,
            password_hash=hash_password(payload.password) if payload.password else None,
            password_changed_at=now if password_changed else None,
            updated_at=now,
        )
    except LastOwnerError as exc:
        raise ApiError(
            status_code=409,
            code=ApiErrorCode.LAST_OWNER_REQUIRED,
            message="At least one active owner must remain",
            error_type="invalid_request_error",
        ) from exc

    if updated is None:
        raise _not_found(admin_id)

    if password_changed:
        from llm_gateway.auth.admin_deps import build_auth_service

        await build_auth_service(container).revoke_all_sessions(admin_id, now=now)

    await record_admin_event_safely(
        container=container,
        principal=principal,
        action="admin.updated",
        target_type="admin",
        target_id=str(admin_id),
        before=admin_snapshot(existing),
        after=admin_snapshot(updated),
    )
    return _detail(updated)
