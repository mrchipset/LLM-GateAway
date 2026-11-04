from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from llm_gateway.auth.admin_auth import AdminPrincipal
from llm_gateway.auth.admin_deps import require_audit_read
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError
from llm_gateway.schemas.admin import (
    AdminAuditEventDetail,
    AdminAuditListResponse,
)
from llm_gateway.storage.repositories import AdminAuditEvent

router = APIRouter(prefix="/admin-audit", tags=["admin-audit"])

PaginationLimit = Annotated[int, Query(ge=1, le=200)]
PaginationOffset = Annotated[int, Query(ge=0)]


def _detail(event: AdminAuditEvent) -> AdminAuditEventDetail:
    return AdminAuditEventDetail(
        id=event.id,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        actor_name=event.actor_name,
        action=event.action,
        target_type=event.target_type,
        target_id=event.target_id,
        before=event.before,
        after=event.after,
        request_id=event.request_id,
        created_at=event.created_at,
    )


def _require_aware(value: datetime, param: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiError.invalid_request(f"{param} must be timezone-aware", param=param)


@router.get("", response_model=AdminAuditListResponse)
async def list_admin_audit(
    _: Annotated[AdminPrincipal, Depends(require_audit_read)],
    container: Annotated[Container, Depends(get_container)],
    actor_id: UUID | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: PaginationLimit = 50,
    offset: PaginationOffset = 0,
) -> AdminAuditListResponse:
    if since is not None:
        _require_aware(since, "since")
    if until is not None:
        _require_aware(until, "until")
    if since is not None and until is not None and since >= until:
        raise ApiError.invalid_request("since must be before until", param="since")

    events, total = await container.admin_audit.list_events(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return AdminAuditListResponse(
        items=[_detail(event) for event in events],
        total=total,
        limit=limit,
        offset=offset,
    )
