"""Request-audit capture orchestration.

The service groups inference requests into sessions, computes deterministic turn
diffs through the pure helpers in :mod:`llm_gateway.services.audit_diff`, and writes
one transaction through :class:`AuditRepository`.

Capture is best effort and strictly subordinate to inference: the safe wrappers in
this module never let storage failures escape to the client-facing path. Client
validation errors (an invalid session header) are the only exception and are
re-raised so the inference route can return a 400 envelope.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from llm_gateway.clock import Clock
from llm_gateway.config import Settings
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.logging import get_logger
from llm_gateway.schemas.chat import ChatCompletionRequest, Usage
from llm_gateway.services.audit_diff import (
    ChangeType,
    PrefixCandidate,
    ResponseSummary,
    bound_parameter_changes,
    build_turn_diff,
    classify_change,
    match_prefix_candidate,
    message_hashes,
    message_preview,
    summarize_response,
    text_hash,
    truncate_snapshot,
)
from llm_gateway.services.usage import extract_token_counts
from llm_gateway.storage.repositories import (
    ApiKeyRecord,
    AuditMatchMethod,
    AuditRepository,
    AuditRequestRecord,
    AuditSessionRecord,
    AuditTurnDiffRecord,
    TenantRepository,
)

logger = get_logger(__name__)

AUDIT_SESSION_HEADER = "x-llm-gateway-session-id"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
PREFIX_WINDOW = timedelta(hours=24)
PREFIX_CANDIDATE_LIMIT = 200
TITLE_PREVIEW_CHARS = 160
PENDING_SESSION_PROVIDER = "unknown"
DEFAULT_AUDIT_WRITE_TIMEOUT_SECONDS = 2.0
AUDIT_PARAMETER_FIELDS = (
    "model",
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "stop",
    "presence_penalty",
    "frequency_penalty",
    "n",
    "seed",
    "user",
    "response_format",
    "tools",
    "tool_choice",
    "stream_options",
)


@dataclass(slots=True)
class AuditTurn:
    """Everything captured at request time, before the response is known."""

    request_id: str
    tenant_id: UUID
    api_key_id: UUID
    api_key_prefix: str
    model_id: str
    is_stream: bool
    created_at: datetime
    session_id: UUID
    external_session_id: str | None
    is_new_session: bool
    parent_request_id: str | None
    turn_index: int
    match_method: AuditMatchMethod
    change_type: ChangeType
    title_preview: str
    messages: list[dict[str, Any]]
    message_hashes: list[str]
    params: dict[str, Any]
    parent_messages: list[dict[str, Any]] | None
    parent_hashes: list[str] | None
    parent_params: dict[str, Any] | None
    parent_usage: dict[str, int] | None
    parent_response: ResponseSummary | None
    session_precreated: bool = False


def _request_params(payload: ChatCompletionRequest, *, model_id: str) -> dict[str, Any]:
    values: dict[str, Any] = {"model": model_id}
    for field in AUDIT_PARAMETER_FIELDS:
        if field == "model":
            continue
        value = getattr(payload, field, None)
        if value is not None:
            values[field] = value
    return values


def _title_preview(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") == "user":
            return message_preview(message, TITLE_PREVIEW_CHARS)
    return ""


def _parent_usage(parent: AuditRequestRecord) -> dict[str, int]:
    return {
        "prompt_tokens": parent.prompt_tokens or 0,
        "completion_tokens": parent.completion_tokens or 0,
        "cached_tokens": parent.cached_tokens or 0,
        "total_tokens": parent.total_tokens or 0,
    }


def _parent_response(parent: AuditRequestRecord) -> ResponseSummary:
    return summarize_response(
        content=parent.response_content,
        tool_calls=parent.response_tool_calls,
        finish_reason=parent.finish_reason,
    )


class AuditService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: AuditRepository,
        tenants: TenantRepository,
        clock: Clock,
    ) -> None:
        self.settings = settings
        self._repository = repository
        self._tenants = tenants
        self._clock = clock

    async def begin(
        self,
        *,
        tenant_id: UUID,
        api_key: ApiKeyRecord,
        request_id: str,
        model_id: str,
        payload: ChatCompletionRequest,
        session_header: str | None,
        is_stream: bool,
    ) -> AuditTurn | None:
        if not self.settings.audit_enabled:
            return None

        tenant = await self._tenants.get_tenant(tenant_id)
        if tenant is None or not tenant.audit_enabled:
            return None

        external_session_id: str | None = None
        if session_header is not None:
            if SESSION_ID_PATTERN.fullmatch(session_header) is None:
                raise ApiError(
                    status_code=400,
                    code=ApiErrorCode.INVALID_SESSION_ID,
                    message="Invalid session id header",
                    error_type="invalid_request_error",
                    param=AUDIT_SESSION_HEADER,
                )
            external_session_id = session_header

        messages: list[dict[str, Any]] = [
            message.model_dump(mode="json", exclude_none=True) for message in payload.messages
        ]
        hashes = message_hashes(messages)
        params = _request_params(payload, model_id=model_id)
        now = self._clock.now()

        parent: AuditRequestRecord | None
        match_method: AuditMatchMethod
        session_precreated = False
        if external_session_id is not None:
            session = await self._repository.get_session_by_external_id(
                tenant_id=tenant_id, external_session_id=external_session_id
            )
            if session is None:
                placeholder = AuditSessionRecord(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    external_session_id=external_session_id,
                    api_key_id=api_key.id,
                    api_key_prefix=api_key.key_prefix,
                    root_request_id=request_id,
                    model_id=model_id,
                    provider=PENDING_SESSION_PROVIDER,
                    title_preview=_title_preview(messages),
                    created_at=now,
                    last_seen_at=now,
                    request_count=0,
                    total_tokens=0,
                )
                stored = await self._repository.ensure_session(session=placeholder)
                session_id = stored.id
                parent = await self._repository.get_latest_request(session_id=session_id)
                session_precreated = True
            else:
                session_id = session.id
                parent = await self._repository.get_latest_request(session_id=session_id)
            is_new_session = parent is None
            turn_index = 1 if parent is None else parent.turn_index + 1
            match_method = "explicit"
        else:
            recent = await self._repository.recent_prefix_requests(
                tenant_id=tenant_id,
                api_key_id=api_key.id,
                since=now - PREFIX_WINDOW,
                limit=PREFIX_CANDIDATE_LIMIT,
            )
            candidates = [
                PrefixCandidate(
                    request_id=record.request_id,
                    session_id=str(record.session_id),
                    turn_index=record.turn_index,
                    message_hashes=tuple(record.message_hashes),
                )
                for record in recent
            ]
            match = match_prefix_candidate(
                current_messages=messages,
                current_hashes=hashes,
                candidates=candidates,
            )
            parent = (
                None
                if match.candidate is None
                else await self._repository.get_request(request_id=match.candidate.request_id)
            )
            if parent is None:
                session_id = uuid4()
                is_new_session = True
                turn_index = 1
                match_method = "new"
            else:
                session_id = parent.session_id
                is_new_session = False
                turn_index = parent.turn_index + 1
                match_method = "prefix"

        parent_hashes = None if parent is None else list(parent.message_hashes)
        return AuditTurn(
            request_id=request_id,
            tenant_id=tenant_id,
            api_key_id=api_key.id,
            api_key_prefix=api_key.key_prefix,
            model_id=model_id,
            is_stream=is_stream,
            created_at=now,
            session_id=session_id,
            external_session_id=external_session_id,
            is_new_session=is_new_session,
            parent_request_id=None if parent is None else parent.request_id,
            turn_index=turn_index,
            match_method=match_method,
            change_type=classify_change(current_hashes=hashes, parent_hashes=parent_hashes),
            title_preview=_title_preview(messages),
            messages=messages,
            message_hashes=hashes,
            params=params,
            parent_messages=None if parent is None else list(parent.request_messages),
            parent_hashes=parent_hashes,
            parent_params=None if parent is None else dict(parent.request_params),
            parent_usage=None if parent is None else _parent_usage(parent),
            parent_response=None if parent is None else _parent_response(parent),
            session_precreated=session_precreated,
        )

    async def finish(
        self,
        *,
        turn: AuditTurn,
        provider: str,
        status: str = "completed",
        response_content: str | None,
        response_tool_calls: list[dict[str, Any]] | None,
        finish_reason: str | None,
        usage: Usage | None,
    ) -> None:
        now = self._clock.now()
        counts = extract_token_counts(usage)
        current_usage = (
            None
            if counts is None
            else {
                "prompt_tokens": counts.prompt_tokens,
                "completion_tokens": counts.completion_tokens,
                "cached_tokens": counts.cached_tokens,
                "total_tokens": counts.total_tokens,
            }
        )
        response_summary = summarize_response(
            content=response_content,
            tool_calls=response_tool_calls,
            finish_reason=finish_reason,
        )
        snapshot = truncate_snapshot(
            messages=turn.messages,
            response_content=response_content,
            max_bytes=self.settings.audit_max_content_bytes,
            extras=(turn.params, response_tool_calls),
        )
        stored_params = snapshot.extras[0] if len(snapshot.extras) > 0 else turn.params
        if not isinstance(stored_params, dict):
            stored_params = turn.params
        stored_tool_calls = snapshot.extras[1] if len(snapshot.extras) > 1 else response_tool_calls
        if not isinstance(stored_tool_calls, list):
            stored_tool_calls = response_tool_calls
        diff = build_turn_diff(
            change_type=turn.change_type,
            current_messages=turn.messages,
            current_hashes=turn.message_hashes,
            parent_messages=turn.parent_messages,
            parent_hashes=turn.parent_hashes,
            current_params=turn.params,
            parent_params=turn.parent_params,
            current_usage=current_usage,
            parent_usage=turn.parent_usage,
            current_response=response_summary,
            parent_response=turn.parent_response,
        )
        # A quarter of the row budget keeps one parameter change well below the
        # total snapshot size once the other diff sections are serialized.
        diff = replace(
            diff,
            parameter_changes=bound_parameter_changes(
                changes=diff.parameter_changes,
                max_value_bytes=self.settings.audit_max_content_bytes // 4,
            ),
        )

        request_record = AuditRequestRecord(
            request_id=turn.request_id,
            session_id=turn.session_id,
            parent_request_id=turn.parent_request_id,
            tenant_id=turn.tenant_id,
            api_key_id=turn.api_key_id,
            turn_index=turn.turn_index,
            match_method=turn.match_method,
            change_type=str(turn.change_type),
            model_id=turn.model_id,
            provider=provider,
            is_stream=turn.is_stream,
            request_messages=snapshot.messages,
            message_hashes=turn.message_hashes,
            request_params=stored_params,
            response_content=snapshot.response_content,
            response_tool_calls=stored_tool_calls,
            response_content_hash=text_hash(response_content),
            finish_reason=finish_reason,
            status=status,
            prompt_tokens=None if counts is None else counts.prompt_tokens,
            completion_tokens=None if counts is None else counts.completion_tokens,
            cached_tokens=None if counts is None else counts.cached_tokens,
            total_tokens=None if counts is None else counts.total_tokens,
            truncated=snapshot.truncated,
            created_at=now,
        )
        total_tokens = 0 if counts is None else counts.total_tokens
        session_record = AuditSessionRecord(
            id=turn.session_id,
            tenant_id=turn.tenant_id,
            external_session_id=turn.external_session_id,
            api_key_id=turn.api_key_id,
            api_key_prefix=turn.api_key_prefix,
            root_request_id=turn.request_id,
            model_id=turn.model_id,
            provider=provider,
            title_preview=turn.title_preview,
            created_at=turn.created_at,
            last_seen_at=now,
            request_count=0 if turn.session_precreated else 1,
            total_tokens=total_tokens,
        )
        diff_record = AuditTurnDiffRecord(
            request_id=turn.request_id,
            previous_request_id=turn.parent_request_id,
            change_type=str(diff.change_type),
            common_prefix=diff.common_prefix,
            added_messages=diff.added_messages,
            modified_messages=diff.modified_messages,
            removed_messages=diff.removed_messages,
            parameter_changes=diff.parameter_changes,
            usage_delta=diff.usage_delta,
            response_change=diff.response_change,
            created_at=now,
        )

        await self._repository.record_turn(
            session=session_record,
            request=request_record,
            diff=diff_record,
        )

    async def fail(
        self,
        *,
        turn: AuditTurn,
        provider: str,
        status: str,
        usage: Usage | None = None,
        response_content: str | None = None,
        response_tool_calls: list[dict[str, Any]] | None = None,
        finish_reason: str | None = None,
    ) -> None:
        await self.finish(
            turn=turn,
            provider=provider,
            status=status,
            response_content=response_content,
            response_tool_calls=response_tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )


def _log_fields(
    *,
    turn: AuditTurn | None,
    request_id: str | None,
    tenant_id: UUID | None,
    session_id: UUID | None,
    model_id: str | None,
    provider: str | None,
    status: str | None,
    error: BaseException,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "request_id": request_id,
        "tenant_id": None if tenant_id is None else str(tenant_id),
        "session_id": None if session_id is None else str(session_id),
        "model_id": model_id,
        "provider": provider,
        "status": status,
        "error": type(error).__name__,
    }
    if turn is not None:
        fields["request_id"] = turn.request_id
        fields["tenant_id"] = str(turn.tenant_id)
        fields["session_id"] = str(turn.session_id)
        fields["model_id"] = turn.model_id
    return {key: value for key, value in fields.items() if value is not None}


async def begin_audit_safely(
    *,
    service: AuditService,
    tenant_id: UUID,
    api_key: ApiKeyRecord,
    request_id: str,
    model_id: str,
    payload: ChatCompletionRequest,
    session_header: str | None,
    is_stream: bool,
) -> AuditTurn | None:
    """Capture the pre-response turn without failing inference.

    ``ApiError`` is the only exception type that escapes, because an invalid session
    header is a client error and must become a 400 response.
    """

    try:
        async with asyncio.timeout(service.settings.audit_write_timeout_seconds):
            return await service.begin(
                tenant_id=tenant_id,
                api_key=api_key,
                request_id=request_id,
                model_id=model_id,
                payload=payload,
                session_header=session_header,
                is_stream=is_stream,
            )
    except ApiError:
        raise
    except Exception as exc:
        logger.warning(
            "audit_begin_failed",
            extra=_log_fields(
                turn=None,
                request_id=request_id,
                tenant_id=tenant_id,
                session_id=None,
                model_id=model_id,
                provider=None,
                status="begin_failed",
                error=exc,
            ),
        )
        return None


async def record_audit_safely(
    *,
    service: AuditService,
    turn: AuditTurn,
    provider: str,
    status: str = "completed",
    response_content: str | None = None,
    response_tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str | None = None,
    usage: Usage | None = None,
) -> None:
    """Persist one audited turn without failing the client-facing response."""

    try:
        async with asyncio.timeout(service.settings.audit_write_timeout_seconds):
            await service.finish(
                turn=turn,
                provider=provider,
                status=status,
                response_content=response_content,
                response_tool_calls=response_tool_calls,
                finish_reason=finish_reason,
                usage=usage,
            )
    except ApiError:
        raise
    except Exception as exc:
        logger.warning(
            "audit_record_failed",
            extra=_log_fields(
                turn=turn,
                request_id=turn.request_id,
                tenant_id=turn.tenant_id,
                session_id=turn.session_id,
                model_id=turn.model_id,
                provider=provider,
                status=status,
                error=exc,
            ),
        )
