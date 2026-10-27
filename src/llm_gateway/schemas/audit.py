"""Strict response shapes for the read-only audit management API.

Privacy contract
----------------
Diffs are intentionally safe to return in both content modes: their message
previews are bounded to 160 characters at capture time. Full messages, response
content, and plaintext parameter values are only present when
``include_content=true``; without content, parameter changes serialize in a
hash-only form. ``AuditTurn.truncated`` and ``AuditRequestDetail.truncated``
describe capture-time truncation, not an API-layer decision.

The response budget (``audit_max_content_bytes``) covers the whole serialized
payload at the route layer, including previews and hashed diffs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

AuditChangeType = Literal["new_session", "continuation", "regeneration", "edit", "truncation"]
AuditStatus = Literal[
    "completed",
    "upstream_error",
    "client_error",
    "client_disconnected",
    "error",
]


class AuditSessionSummary(BaseModel):
    """One audited conversation, without any message content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    tenant_id: UUID
    external_session_id: str | None
    api_key_id: UUID
    api_key_prefix: str
    model_id: str
    provider: str
    title_preview: str
    created_at: datetime
    last_seen_at: datetime
    request_count: int
    total_tokens: int


class AuditSessionPage(BaseModel):
    """A page of audited sessions; newest ``last_seen_at`` first."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[AuditSessionSummary]
    total: int
    limit: int
    offset: int


class AuditMessageRef(BaseModel):
    """A short, bounded reference to one added or removed message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int
    role: str
    hash: str
    preview: str


class AuditMessageModification(BaseModel):
    """A bounded before/after reference for one modified message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int
    role: str
    before_hash: str
    after_hash: str
    before_preview: str
    after_preview: str


class AuditParameterChange(BaseModel):
    """One parameter difference; plaintext or a bounded hash-only form.

    Plaintext entries serialize as ``{"from": ..., "to": ...}``. When capture
    bounded a value, or when the caller omitted ``include_content``, entries
    serialize as ``{"from_hash": ..., "to_hash": ..., "truncated": true}`` and
    never expose the original value.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    from_value: object | None = Field(default=None, alias="from")
    to_value: object | None = Field(default=None, alias="to")
    from_hash: str | None = None
    to_hash: str | None = None
    truncated: bool = False

    @model_serializer(mode="wrap")
    def _serialize_change(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data = handler(self)
        hashed = self.from_hash is not None or self.to_hash is not None or self.truncated
        if hashed:
            for key in ("from", "to", "from_value", "to_value"):
                data.pop(key, None)
        else:
            for key in ("from_hash", "to_hash", "truncated"):
                data.pop(key, None)
        return data


class AuditResponseChange(BaseModel):
    """Summary of what changed in the completion across one turn boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content_changed: bool
    previous_content_hash: str | None
    content_hash: str | None
    finish_reason_changed: bool
    previous_finish_reason: str | None
    finish_reason: str | None
    tool_calls_added: int
    tool_calls_removed: int
    tool_call_names: list[str]


class AuditDiff(BaseModel):
    """Deterministic structural difference between a turn and its predecessor.

    Message previews are intentionally short (at most 160 characters at capture
    time) and are returned in both modes: they are bounded by design and are the
    value of the diff. Full messages, response content, and plaintext parameter
    values are only returned when ``include_content=true``. Without content,
    every ``parameter_changes`` entry is hashed (``from_hash``/``to_hash``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    change_type: AuditChangeType
    common_prefix: int
    added_messages: list[AuditMessageRef]
    modified_messages: list[AuditMessageModification]
    removed_messages: list[AuditMessageRef]
    parameter_changes: dict[str, AuditParameterChange]
    usage_delta: dict[str, int]
    response_change: AuditResponseChange


class AuditTurn(BaseModel):
    """One audited turn inside a session.

    Content fields are ``None`` unless the caller requested ``include_content``.
    ``truncated`` reflects capture-time truncation of the stored request, not a
    decision made by this endpoint. The diff is always present when stored and
    only carries bounded previews plus (when content is included) plaintext
    parameter values.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    parent_request_id: str | None
    turn_index: int
    match_method: Literal["explicit", "prefix", "new"]
    change_type: AuditChangeType
    model_id: str
    provider: str
    is_stream: bool
    status: AuditStatus
    finish_reason: str | None
    truncated: bool
    created_at: datetime
    prompt_tokens: int | None
    completion_tokens: int | None
    cached_tokens: int | None
    total_tokens: int | None
    request_message_count: int
    diff: AuditDiff | None
    request_messages: list[dict[str, object]] | None = None
    request_params: dict[str, object] | None = None
    response_content: str | None = None
    response_tool_calls: list[dict[str, object]] | None = None


class AuditSessionDetailResponse(BaseModel):
    """Session detail; per-turn ``truncated`` reports capture-time truncation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session: AuditSessionSummary
    turns: list[AuditTurn]


class AuditRequestDetail(BaseModel):
    """A single audited request including its stored content.

    ``truncated`` reflects capture-time truncation of the stored row; the
    endpoint does not re-truncate content.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    session_id: UUID
    tenant_id: UUID
    api_key_id: UUID
    parent_request_id: str | None
    turn_index: int
    match_method: Literal["explicit", "prefix", "new"]
    change_type: AuditChangeType
    model_id: str
    provider: str
    is_stream: bool
    status: AuditStatus
    finish_reason: str | None
    truncated: bool
    created_at: datetime
    prompt_tokens: int | None
    completion_tokens: int | None
    cached_tokens: int | None
    total_tokens: int | None
    request_messages: list[dict[str, object]]
    request_params: dict[str, object]
    response_content: str | None
    response_tool_calls: list[dict[str, object]] | None
    response_content_hash: str | None


class AuditRequestDetailResponse(BaseModel):
    """Request detail plus its turn diff; ``truncated`` mirrors the stored row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: AuditRequestDetail
    diff: AuditDiff | None
    truncated: bool
