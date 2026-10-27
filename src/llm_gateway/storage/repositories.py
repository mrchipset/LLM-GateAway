from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from llm_gateway.providers.base import ProviderName

_HEX_DIGITS = frozenset("0123456789abcdef")


class TimeBucket(StrEnum):
    HOUR = "hour"
    DAY = "day"


DEFAULT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def _require_non_blank(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be blank")


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _require_key_hash(value: str) -> None:
    if len(value) != 64 or any(char not in _HEX_DIGITS for char in value):
        raise ValueError("key_hash must be 64 lowercase hex characters")


def _require_uuid(value: object, field: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{field} must be a UUID")


def _require_optional_positive_int(value: object, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer or None")


def _require_optional_non_negative_int(value: object, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer or None")


def _require_optional_aware(value: datetime | None, field: str) -> None:
    if value is not None:
        _require_aware(value, field)


@dataclass(frozen=True, slots=True)
class Tenant:
    """An organizational label that owns API keys."""

    id: UUID
    name: str
    created_at: datetime
    monthly_token_quota: int | None = None
    requests_per_minute: int | None = None
    audit_enabled: bool = False

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_non_blank(self.name, "name")
        _require_aware(self.created_at, "created_at")
        _require_optional_positive_int(self.monthly_token_quota, "monthly_token_quota")
        _require_optional_positive_int(self.requests_per_minute, "requests_per_minute")


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Public model name plus the provider deployment that serves it."""

    id: str
    provider: ProviderName
    upstream_model: str
    created_at: datetime
    enabled: bool = True

    def __post_init__(self) -> None:
        _require_non_blank(self.id, "id")
        _require_non_blank(self.upstream_model, "upstream_model")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    """Persisted API key metadata. The plaintext secret is never stored."""

    id: UUID
    tenant_id: UUID
    name: str
    key_hash: str
    key_prefix: str
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.tenant_id, "tenant_id")
        _require_non_blank(self.name, "name")
        _require_key_hash(self.key_hash)
        _require_aware(self.created_at, "created_at")
        for field in ("expires_at", "revoked_at", "last_used_at"):
            value = getattr(self, field)
            if value is not None:
                _require_aware(value, field)


def _require_non_negative_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _require_provider(value: object, field: str) -> None:
    if not isinstance(value, ProviderName):
        raise ValueError(f"{field} must be a ProviderName")


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """One successfully served inference request and its token counts."""

    id: UUID
    request_id: str
    tenant_id: UUID
    api_key_id: UUID
    model_id: str
    provider: ProviderName
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int
    created_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_non_blank(self.request_id, "request_id")
        _require_uuid(self.tenant_id, "tenant_id")
        _require_uuid(self.api_key_id, "api_key_id")
        _require_non_blank(self.model_id, "model_id")
        _require_provider(self.provider, "provider")
        _require_non_negative_int(self.prompt_tokens, "prompt_tokens")
        _require_non_negative_int(self.completion_tokens, "completion_tokens")
        _require_non_negative_int(self.total_tokens, "total_tokens")
        _require_non_negative_int(self.cached_tokens, "cached_tokens")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class UsageTotals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0

    def __post_init__(self) -> None:
        for field in (
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "total_tokens",
            "requests",
        ):
            _require_non_negative_int(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class ModelUsage:
    model_id: str
    provider: ProviderName
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    requests: int

    def __post_init__(self) -> None:
        _require_non_blank(self.model_id, "model_id")
        _require_provider(self.provider, "provider")
        for field in (
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "total_tokens",
            "requests",
        ):
            _require_non_negative_int(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class KeyUsage:
    api_key_id: UUID
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    requests: int

    def __post_init__(self) -> None:
        _require_uuid(self.api_key_id, "api_key_id")
        for field in (
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "total_tokens",
            "requests",
        ):
            _require_non_negative_int(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class UsagePoint:
    bucket_start: datetime
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    requests: int

    def __post_init__(self) -> None:
        _require_aware(self.bucket_start, "bucket_start")
        for field in (
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "total_tokens",
            "requests",
        ):
            _require_non_negative_int(getattr(self, field), field)


class DuplicateModelError(Exception):
    def __init__(self, model_id: str) -> None:
        super().__init__(f"model '{model_id}' already exists")
        self.model_id = model_id


class DuplicateTenantError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"tenant '{name}' already exists")
        self.name = name


class UnknownTenantError(Exception):
    """Raised when a write references a tenant that no longer exists."""

    def __init__(self, tenant_id: UUID) -> None:
        super().__init__(f"tenant '{tenant_id}' does not exist")
        self.tenant_id = tenant_id


class DuplicateApiKeyError(Exception):
    def __init__(self) -> None:
        super().__init__("an API key with the same hash already exists")


@dataclass(frozen=True, slots=True)
class TenantLimitPatch:
    """Partial limit update; only fields with a true ``set_*`` flag are written."""

    monthly_token_quota: int | None = None
    requests_per_minute: int | None = None
    audit_enabled: bool | None = None
    set_monthly_token_quota: bool = False
    set_requests_per_minute: bool = False
    set_audit_enabled: bool = False


class TenantRepository(Protocol):
    async def create_tenant(self, tenant: Tenant) -> Tenant: ...

    async def get_tenant(self, tenant_id: UUID) -> Tenant | None: ...

    async def list_tenants(self, *, limit: int, offset: int) -> tuple[Sequence[Tenant], int]: ...

    async def set_tenant_limits(
        self,
        tenant_id: UUID,
        *,
        patch: TenantLimitPatch,
    ) -> Tenant | None: ...


class UsageRepository(Protocol):
    async def record(self, record: UsageRecord) -> None: ...

    async def token_total(self, *, tenant_id: UUID, since: datetime, until: datetime) -> int: ...

    async def summary_by_model(
        self,
        *,
        tenant_id: UUID | None,
        model_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Sequence[ModelUsage]: ...

    async def summary_by_key(
        self,
        *,
        tenant_id: UUID | None,
        model_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Sequence[KeyUsage]: ...

    async def summary_series(
        self,
        *,
        tenant_id: UUID | None,
        model_id: str | None,
        since: datetime | None,
        until: datetime | None,
        bucket: TimeBucket,
    ) -> Sequence[UsagePoint]: ...


class ModelRepository(Protocol):
    async def list_models(
        self, *, limit: int, offset: int, enabled_only: bool = False
    ) -> tuple[Sequence[ModelConfig], int]: ...

    async def get_model(self, model_id: str) -> ModelConfig | None: ...

    async def create_model(self, model: ModelConfig) -> ModelConfig: ...

    async def delete_model(self, model_id: str) -> bool: ...


class ApiKeyRepository(Protocol):
    async def create_key(self, record: ApiKeyRecord) -> ApiKeyRecord: ...

    async def get_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None: ...

    async def get_key(self, key_id: UUID) -> ApiKeyRecord | None: ...

    async def get_keys(self, key_ids: Sequence[UUID]) -> Sequence[ApiKeyRecord]: ...

    async def list_keys(
        self, *, limit: int, offset: int, tenant_id: UUID | None = None
    ) -> tuple[Sequence[ApiKeyRecord], int]: ...

    async def revoke_key(self, key_id: UUID, revoked_at: datetime) -> bool: ...

    async def touch_last_used(self, key_id: UUID, used_at: datetime) -> None: ...


AuditMatchMethod = Literal["explicit", "prefix", "new"]


def _require_non_blank_limited(value: str, field: str, *, max_length: int) -> None:
    _require_non_blank(value, field)
    if len(value) > max_length:
        raise ValueError(f"{field} must be at most {max_length} characters")


@dataclass(frozen=True, slots=True)
class AuditSessionRecord:
    """A logical conversation grouping one or more audited requests."""

    id: UUID
    tenant_id: UUID
    external_session_id: str | None
    api_key_id: UUID
    api_key_prefix: str
    root_request_id: str
    model_id: str
    provider: str
    title_preview: str
    created_at: datetime
    last_seen_at: datetime
    request_count: int
    total_tokens: int

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_uuid(self.tenant_id, "tenant_id")
        _require_uuid(self.api_key_id, "api_key_id")
        if self.external_session_id is not None:
            _require_non_blank_limited(
                self.external_session_id, "external_session_id", max_length=64
            )
        _require_non_blank_limited(self.api_key_prefix, "api_key_prefix", max_length=16)
        _require_non_blank_limited(self.root_request_id, "root_request_id", max_length=64)
        _require_non_blank(self.model_id, "model_id")
        _require_non_blank(self.provider, "provider")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.last_seen_at, "last_seen_at")
        _require_non_negative_int(self.request_count, "request_count")
        _require_non_negative_int(self.total_tokens, "total_tokens")


@dataclass(frozen=True, slots=True)
class AuditRequestRecord:
    """One audited inference turn, independent from the usage ledger."""

    request_id: str
    session_id: UUID
    parent_request_id: str | None
    tenant_id: UUID
    api_key_id: UUID
    turn_index: int
    match_method: AuditMatchMethod
    change_type: str
    model_id: str
    provider: str
    is_stream: bool
    request_messages: list[dict[str, Any]]
    message_hashes: list[str]
    request_params: dict[str, Any]
    response_content: str | None
    response_tool_calls: list[dict[str, Any]] | None
    response_content_hash: str | None
    finish_reason: str | None
    status: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cached_tokens: int | None
    total_tokens: int | None
    truncated: bool
    created_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank_limited(self.request_id, "request_id", max_length=64)
        _require_uuid(self.session_id, "session_id")
        _require_uuid(self.tenant_id, "tenant_id")
        _require_uuid(self.api_key_id, "api_key_id")
        if self.parent_request_id is not None:
            _require_non_blank_limited(self.parent_request_id, "parent_request_id", max_length=64)
        _require_non_negative_int(self.turn_index, "turn_index")
        if self.match_method not in ("explicit", "prefix", "new"):
            raise ValueError("match_method must be one of 'explicit', 'prefix', 'new'")
        _require_non_blank(self.change_type, "change_type")
        _require_non_blank(self.model_id, "model_id")
        _require_non_blank(self.provider, "provider")
        _require_non_blank(self.status, "status")
        for field in ("prompt_tokens", "completion_tokens", "cached_tokens", "total_tokens"):
            _require_optional_non_negative_int(getattr(self, field), field)
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class AuditRequestSummary:
    """Timeline projection of a turn without message/response bodies."""

    request_id: str
    session_id: UUID
    parent_request_id: str | None
    tenant_id: UUID
    api_key_id: UUID
    turn_index: int
    match_method: AuditMatchMethod
    change_type: str
    model_id: str
    provider: str
    is_stream: bool
    finish_reason: str | None
    status: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cached_tokens: int | None
    total_tokens: int | None
    truncated: bool
    created_at: datetime
    request_message_count: int

    def __post_init__(self) -> None:
        _require_non_blank_limited(self.request_id, "request_id", max_length=64)
        _require_uuid(self.session_id, "session_id")
        _require_uuid(self.tenant_id, "tenant_id")
        _require_uuid(self.api_key_id, "api_key_id")
        if self.parent_request_id is not None:
            _require_non_blank_limited(self.parent_request_id, "parent_request_id", max_length=64)
        _require_non_negative_int(self.turn_index, "turn_index")
        if self.match_method not in ("explicit", "prefix", "new"):
            raise ValueError("match_method must be one of 'explicit', 'prefix', 'new'")
        _require_non_blank(self.change_type, "change_type")
        _require_non_blank(self.model_id, "model_id")
        _require_non_blank(self.provider, "provider")
        _require_non_blank(self.status, "status")
        for field in ("prompt_tokens", "completion_tokens", "cached_tokens", "total_tokens"):
            _require_optional_non_negative_int(getattr(self, field), field)
        _require_non_negative_int(self.request_message_count, "request_message_count")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class AuditTurnDiffRecord:
    """Structural difference between a turn and its predecessor."""

    request_id: str
    previous_request_id: str | None
    change_type: str
    common_prefix: int
    added_messages: list[dict[str, Any]]
    modified_messages: list[dict[str, Any]]
    removed_messages: list[dict[str, Any]]
    parameter_changes: dict[str, Any]
    usage_delta: dict[str, Any]
    response_change: dict[str, Any]
    created_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank_limited(self.request_id, "request_id", max_length=64)
        if self.previous_request_id is not None:
            _require_non_blank_limited(
                self.previous_request_id, "previous_request_id", max_length=64
            )
        _require_non_blank(self.change_type, "change_type")
        _require_non_negative_int(self.common_prefix, "common_prefix")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class AuditSessionFilters:
    """Query filters for listing audit sessions; the window is half-open."""

    tenant_id: UUID | None = None
    api_key_id: UUID | None = None
    model_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    q: str | None = None

    def __post_init__(self) -> None:
        if self.tenant_id is not None:
            _require_uuid(self.tenant_id, "tenant_id")
        if self.api_key_id is not None:
            _require_uuid(self.api_key_id, "api_key_id")
        _require_optional_aware(self.since, "since")
        _require_optional_aware(self.until, "until")
        if self.since is not None and self.until is not None and self.since >= self.until:
            raise ValueError("since must be before until")


@dataclass(frozen=True, slots=True)
class AuditSessionPage:
    items: list[AuditSessionRecord]
    total: int

    def __post_init__(self) -> None:
        _require_non_negative_int(self.total, "total")


@dataclass(frozen=True, slots=True)
class AuditPrefixRecord:
    """Hash-only view of an auditable request used for session prefix matching.

    Deliberately excludes message/params/response payloads so the fallback query
    never loads full snapshots for every recent request.
    """

    request_id: str
    session_id: UUID
    turn_index: int
    message_hashes: list[str]
    created_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank_limited(self.request_id, "request_id", max_length=64)
        _require_uuid(self.session_id, "session_id")
        _require_non_negative_int(self.turn_index, "turn_index")
        if not self.message_hashes:
            raise ValueError("message_hashes must contain at least one hash")
        for digest in self.message_hashes:
            _require_non_blank(digest, "message_hashes")
        _require_aware(self.created_at, "created_at")


class AuditRepository(Protocol):
    async def record_turn(
        self,
        *,
        session: AuditSessionRecord,
        request: AuditRequestRecord,
        diff: AuditTurnDiffRecord | None,
    ) -> None: ...

    async def get_session_by_external_id(
        self, *, tenant_id: UUID, external_session_id: str
    ) -> AuditSessionRecord | None: ...

    async def ensure_session(self, *, session: AuditSessionRecord) -> AuditSessionRecord:
        """Return the stored session, inserting it when absent.

        Looks up by id first, then by ``(tenant_id, external_session_id)`` when
        the external id is set, so concurrent first requests converge on one row.
        The insert path persists the caller's stats exactly as provided.
        """
        ...

    async def get_latest_request(self, *, session_id: UUID) -> AuditRequestRecord | None: ...

    async def recent_prefix_requests(
        self, *, tenant_id: UUID, api_key_id: UUID, since: datetime, limit: int
    ) -> list[AuditPrefixRecord]:
        """Newest-first hash-only view of recent requests for prefix matching."""
        ...

    async def list_sessions(
        self, *, filters: AuditSessionFilters, limit: int, offset: int
    ) -> AuditSessionPage: ...

    async def get_session(self, *, session_id: UUID) -> AuditSessionRecord | None: ...

    async def list_session_requests(self, *, session_id: UUID) -> list[AuditRequestRecord]: ...

    async def list_session_request_summaries(
        self, *, session_id: UUID
    ) -> list[AuditRequestSummary]:
        """Timeline view ordered by ``turn_index, created_at, request_id``."""
        ...

    async def get_diffs(self, *, request_ids: Sequence[str]) -> dict[str, AuditTurnDiffRecord]: ...

    async def get_request(self, *, request_id: str) -> AuditRequestRecord | None: ...

    async def get_diff(self, *, request_id: str) -> AuditTurnDiffRecord | None: ...
