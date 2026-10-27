"""Read-only audit management API.

Privacy policy
--------------
Audit content is opt-in per request. ``include_content=false`` (the default for
session detail) never returns stored messages, request parameters, response
content, or response tool calls. Diffs are always returned: they carry only the
intentionally short (≤160 characters) message previews produced at capture time
and, without content, every parameter change is reduced to a hash-only form.
Bounded previews are considered safe and are the value of the diff.

Content budget
--------------
``settings.audit_max_content_bytes`` limits the *whole* returned payload, not
just full message bodies. Both modes measure the canonical UTF-8 JSON of the
response after it has been built: the ``turns`` array for session detail and
``{request, diff}`` for request detail. Over-budget responses fail with 413
``audit_content_too_large``; nothing is silently truncated at this layer.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from llm_gateway.auth.dependencies import require_master_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.audit import (
    AuditChangeType,
    AuditDiff,
    AuditRequestDetail,
    AuditRequestDetailResponse,
    AuditSessionDetailResponse,
    AuditSessionPage,
    AuditSessionSummary,
    AuditStatus,
    AuditTurn,
)
from llm_gateway.services.audit_diff import bound_parameter_changes
from llm_gateway.storage.repositories import (
    AuditRequestRecord,
    AuditRequestSummary,
    AuditSessionFilters,
    AuditSessionRecord,
    AuditTurnDiffRecord,
)

router = APIRouter(dependencies=[Depends(require_master_key)])

SESSION_NOT_FOUND_MESSAGE = "Audit session was not found"
REQUEST_NOT_FOUND_MESSAGE = "Audit request was not found"
CONTENT_TOO_LARGE_MESSAGE = (
    "Audit content exceeds the configured size limit; fetch requests individually"
)


def _require_aware(value: datetime, param: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiError.invalid_request(
            f"{param} must be timezone-aware",
            param=param,
        )


def _validate_window(since: datetime, until: datetime | None) -> None:
    _require_aware(since, "since")
    if until is not None:
        _require_aware(until, "until")
    if until is not None and since >= until:
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


def _ensure_payload_budget(container: Container, payload: object) -> None:
    size = len(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if size > container.settings.audit_max_content_bytes:
        raise ApiError(
            status_code=413,
            code=ApiErrorCode.AUDIT_CONTENT_TOO_LARGE,
            message=CONTENT_TOO_LARGE_MESSAGE,
            error_type="invalid_request_error",
        )


def _to_session_summary(record: AuditSessionRecord) -> AuditSessionSummary:
    return AuditSessionSummary(
        id=record.id,
        tenant_id=record.tenant_id,
        external_session_id=record.external_session_id,
        api_key_id=record.api_key_id,
        api_key_prefix=record.api_key_prefix,
        model_id=record.model_id,
        provider=record.provider,
        title_preview=record.title_preview,
        created_at=record.created_at,
        last_seen_at=record.last_seen_at,
        request_count=record.request_count,
        total_tokens=record.total_tokens,
    )


def _to_diff(record: AuditTurnDiffRecord, *, include_content: bool) -> AuditDiff:
    changes: dict[str, dict[str, object]] = (
        record.parameter_changes
        if include_content
        else bound_parameter_changes(changes=record.parameter_changes, max_value_bytes=0)
    )
    return AuditDiff.model_validate(
        {
            "change_type": record.change_type,
            "common_prefix": record.common_prefix,
            "added_messages": record.added_messages,
            "modified_messages": record.modified_messages,
            "removed_messages": record.removed_messages,
            "parameter_changes": changes,
            "usage_delta": record.usage_delta,
            "response_change": record.response_change,
        }
    )


def _turn_from_record(
    record: AuditRequestRecord,
    diff: AuditTurnDiffRecord | None,
    *,
    include_content: bool,
) -> AuditTurn:
    return AuditTurn(
        request_id=record.request_id,
        parent_request_id=record.parent_request_id,
        turn_index=record.turn_index,
        match_method=record.match_method,
        change_type=cast(AuditChangeType, record.change_type),
        model_id=record.model_id,
        provider=record.provider,
        is_stream=record.is_stream,
        status=cast(AuditStatus, record.status),
        finish_reason=record.finish_reason,
        truncated=record.truncated,
        created_at=record.created_at,
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        cached_tokens=record.cached_tokens,
        total_tokens=record.total_tokens,
        request_message_count=len(record.request_messages),
        diff=None if diff is None else _to_diff(diff, include_content=include_content),
        request_messages=record.request_messages if include_content else None,
        request_params=record.request_params if include_content else None,
        response_content=record.response_content if include_content else None,
        response_tool_calls=record.response_tool_calls if include_content else None,
    )


def _turn_from_summary(
    summary: AuditRequestSummary,
    diff: AuditTurnDiffRecord | None,
) -> AuditTurn:
    return AuditTurn(
        request_id=summary.request_id,
        parent_request_id=summary.parent_request_id,
        turn_index=summary.turn_index,
        match_method=summary.match_method,
        change_type=cast(AuditChangeType, summary.change_type),
        model_id=summary.model_id,
        provider=summary.provider,
        is_stream=summary.is_stream,
        status=cast(AuditStatus, summary.status),
        finish_reason=summary.finish_reason,
        truncated=summary.truncated,
        created_at=summary.created_at,
        prompt_tokens=summary.prompt_tokens,
        completion_tokens=summary.completion_tokens,
        cached_tokens=summary.cached_tokens,
        total_tokens=summary.total_tokens,
        request_message_count=summary.request_message_count,
        diff=None if diff is None else _to_diff(diff, include_content=False),
    )


def _to_request_detail(record: AuditRequestRecord) -> AuditRequestDetail:
    return AuditRequestDetail(
        request_id=record.request_id,
        session_id=record.session_id,
        tenant_id=record.tenant_id,
        api_key_id=record.api_key_id,
        parent_request_id=record.parent_request_id,
        turn_index=record.turn_index,
        match_method=record.match_method,
        change_type=cast(AuditChangeType, record.change_type),
        model_id=record.model_id,
        provider=record.provider,
        is_stream=record.is_stream,
        status=cast(AuditStatus, record.status),
        finish_reason=record.finish_reason,
        truncated=record.truncated,
        created_at=record.created_at,
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        cached_tokens=record.cached_tokens,
        total_tokens=record.total_tokens,
        request_messages=record.request_messages,
        request_params=record.request_params,
        response_content=record.response_content,
        response_tool_calls=record.response_tool_calls,
        response_content_hash=record.response_content_hash,
    )


@router.get("/audit/sessions", response_model=AuditSessionPage)
async def list_audit_sessions(
    container: Annotated[Container, Depends(get_container)],
    since: datetime,
    tenant_id: UUID | None = None,
    api_key_id: UUID | None = None,
    model_id: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    until: datetime | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditSessionPage:
    _validate_window(since, until)
    await _ensure_tenant(container, tenant_id)

    page = await container.audit.list_sessions(
        filters=AuditSessionFilters(
            tenant_id=tenant_id,
            api_key_id=api_key_id,
            model_id=model_id,
            since=since,
            until=until,
            q=q,
        ),
        limit=limit,
        offset=offset,
    )
    return AuditSessionPage(
        items=[_to_session_summary(item) for item in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/audit/sessions/{session_id}", response_model=AuditSessionDetailResponse)
async def get_audit_session(
    container: Annotated[Container, Depends(get_container)],
    session_id: UUID,
    include_content: bool = False,
) -> AuditSessionDetailResponse:
    session = await container.audit.get_session(session_id=session_id)
    if session is None:
        raise ApiError(
            status_code=404,
            code=ApiErrorCode.AUDIT_SESSION_NOT_FOUND,
            message=SESSION_NOT_FOUND_MESSAGE,
            error_type="invalid_request_error",
            param="session_id",
        )

    turns: list[AuditTurn]
    if include_content:
        records = await container.audit.list_session_requests(session_id=session_id)
        diffs = await container.audit.get_diffs(
            request_ids=[record.request_id for record in records]
        )
        turns = [
            _turn_from_record(
                record,
                diffs.get(record.request_id),
                include_content=True,
            )
            for record in records
        ]
    else:
        summaries = await container.audit.list_session_request_summaries(session_id=session_id)
        summaries_diffs = await container.audit.get_diffs(
            request_ids=[summary.request_id for summary in summaries]
        )
        turns = [
            _turn_from_summary(summary, summaries_diffs.get(summary.request_id))
            for summary in summaries
        ]

    _ensure_payload_budget(
        container,
        [turn.model_dump(mode="json", by_alias=True) for turn in turns],
    )
    return AuditSessionDetailResponse(
        session=_to_session_summary(session),
        turns=turns,
    )


@router.get("/audit/requests/{request_id}", response_model=AuditRequestDetailResponse)
async def get_audit_request(
    container: Annotated[Container, Depends(get_container)],
    request_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> AuditRequestDetailResponse:
    record = await container.audit.get_request(request_id=request_id)
    if record is None:
        raise ApiError(
            status_code=404,
            code=ApiErrorCode.AUDIT_REQUEST_NOT_FOUND,
            message=REQUEST_NOT_FOUND_MESSAGE,
            error_type="invalid_request_error",
            param="request_id",
        )

    detail = _to_request_detail(record)
    diff_record = await container.audit.get_diff(request_id=request_id)
    diff = None if diff_record is None else _to_diff(diff_record, include_content=True)
    _ensure_payload_budget(
        container,
        {
            "request": detail.model_dump(mode="json", by_alias=True),
            "diff": None if diff is None else diff.model_dump(mode="json", by_alias=True),
        },
    )
    return AuditRequestDetailResponse(
        request=detail,
        diff=diff,
        truncated=record.truncated,
    )
