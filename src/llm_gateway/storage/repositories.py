from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from llm_gateway.providers.base import ProviderName

_HEX_DIGITS = frozenset("0123456789abcdef")


class TimeBucket(StrEnum):
    HOUR = "hour"
    DAY = "day"


class ModelAccessMode(StrEnum):
    """How a tenant's model permissions are evaluated."""

    ALL = "all"
    ALLOWLIST = "allowlist"


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


def _require_optional_uuid_value(value: object, field: str) -> None:
    if value is not None and not isinstance(value, UUID):
        raise ValueError(f"{field} must be a UUID or None")


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


def _require_money(value: object, field: str, *, allow_zero: bool = True) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{field} must be {'non-negative' if allow_zero else 'positive'}")


def _require_optional_money(value: object, field: str) -> None:
    if value is None:
        return
    _require_money(value, field)


def _require_currency(value: object, field: str) -> None:
    if not isinstance(value, str) or len(value) != 3 or not value.isupper():
        raise ValueError(f"{field} must be a 3-letter uppercase currency code")


@dataclass(frozen=True, slots=True)
class Tenant:
    """An organizational label that owns API keys."""

    id: UUID
    name: str
    created_at: datetime
    monthly_token_quota: int | None = None
    requests_per_minute: int | None = None
    audit_enabled: bool = False
    model_access_mode: ModelAccessMode = ModelAccessMode.ALL
    plan_tokens: int | None = None
    plan_allow_overage: bool = False
    monthly_cost_budget: Decimal | None = None
    audit_retention_days: int | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_non_blank(self.name, "name")
        _require_aware(self.created_at, "created_at")
        _require_optional_positive_int(self.monthly_token_quota, "monthly_token_quota")
        _require_optional_positive_int(self.requests_per_minute, "requests_per_minute")
        _require_optional_positive_int(self.plan_tokens, "plan_tokens")
        if not isinstance(self.plan_allow_overage, bool):
            raise ValueError("plan_allow_overage must be a boolean")
        _require_optional_money(self.monthly_cost_budget, "monthly_cost_budget")
        if self.audit_retention_days is not None and (
            not isinstance(self.audit_retention_days, int)
            or isinstance(self.audit_retention_days, bool)
            or self.audit_retention_days < 0
        ):
            raise ValueError("audit_retention_days must be a non-negative integer or None")
        if not isinstance(self.model_access_mode, ModelAccessMode):
            raise ValueError("model_access_mode must be a ModelAccessMode")


@dataclass(frozen=True, slots=True)
class ModelAccess:
    """A tenant's resolved model permissions.

    ``ALLOWLIST`` with an empty ``model_ids`` means "no models", which is a
    deliberate way to block a tenant without deleting its keys.
    """

    mode: ModelAccessMode
    model_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ModelAccessMode):
            raise ValueError("mode must be a ModelAccessMode")
        for model_id in self.model_ids:
            _require_non_blank(model_id, "model_id")

    def allows(self, model_id: str) -> bool:
        return self.mode is ModelAccessMode.ALL or model_id in self.model_ids


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
class ModelPrice:
    """A versioned price list for one model, in the deployment currency.

    Prices are per million tokens. ``cached_input_per_million`` falls back to
    ``input_per_million`` when unset.
    """

    id: UUID
    model_id: str
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal | None
    currency: str
    effective_from: datetime
    created_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_non_blank(self.model_id, "model_id")
        _require_money(self.input_per_million, "input_per_million")
        _require_money(self.output_per_million, "output_per_million")
        _require_optional_money(self.cached_input_per_million, "cached_input_per_million")
        _require_currency(self.currency, "currency")
        _require_aware(self.effective_from, "effective_from")
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
    trace_id: str | None = None
    covered_tokens: int = 0
    billable_tokens: int = 0
    list_cost: Decimal | None = None
    billed_cost: Decimal | None = None

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
        _require_non_negative_int(self.covered_tokens, "covered_tokens")
        _require_non_negative_int(self.billable_tokens, "billable_tokens")
        _require_optional_money(self.list_cost, "list_cost")
        _require_optional_money(self.billed_cost, "billed_cost")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class UsageTotals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0
    covered_tokens: int = 0
    billable_tokens: int = 0
    list_cost: Decimal = Decimal("0")
    billed_cost: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for field in (
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "total_tokens",
            "requests",
            "covered_tokens",
            "billable_tokens",
        ):
            _require_non_negative_int(getattr(self, field), field)
        _require_money(self.list_cost, "list_cost")
        _require_money(self.billed_cost, "billed_cost")


@dataclass(frozen=True, slots=True)
class MonthlyUsage:
    """Aggregated usage for one billing period, used by enforcement and reporting."""

    total_tokens: int = 0
    covered_tokens: int = 0
    billable_tokens: int = 0
    billed_cost: Decimal = Decimal("0")
    list_cost: Decimal = Decimal("0")
    requests: int = 0

    def __post_init__(self) -> None:
        for field in ("total_tokens", "covered_tokens", "billable_tokens", "requests"):
            _require_non_negative_int(getattr(self, field), field)
        _require_money(self.billed_cost, "billed_cost")
        _require_money(self.list_cost, "list_cost")


@dataclass(frozen=True, slots=True)
class ModelUsage:
    model_id: str
    provider: ProviderName
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    requests: int
    covered_tokens: int = 0
    billable_tokens: int = 0
    list_cost: Decimal = Decimal("0")
    billed_cost: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _require_non_blank(self.model_id, "model_id")
        _require_provider(self.provider, "provider")
        for field in (
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "total_tokens",
            "requests",
            "covered_tokens",
            "billable_tokens",
        ):
            _require_non_negative_int(getattr(self, field), field)
        _require_money(self.list_cost, "list_cost")
        _require_money(self.billed_cost, "billed_cost")


@dataclass(frozen=True, slots=True)
class KeyUsage:
    api_key_id: UUID
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    requests: int
    covered_tokens: int = 0
    billable_tokens: int = 0
    list_cost: Decimal = Decimal("0")
    billed_cost: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _require_uuid(self.api_key_id, "api_key_id")
        for field in (
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "total_tokens",
            "requests",
            "covered_tokens",
            "billable_tokens",
        ):
            _require_non_negative_int(getattr(self, field), field)
        _require_money(self.list_cost, "list_cost")
        _require_money(self.billed_cost, "billed_cost")


@dataclass(frozen=True, slots=True)
class UsagePoint:
    bucket_start: datetime
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    requests: int
    covered_tokens: int = 0
    billable_tokens: int = 0
    list_cost: Decimal = Decimal("0")
    billed_cost: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _require_aware(self.bucket_start, "bucket_start")
        for field in (
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "total_tokens",
            "requests",
            "covered_tokens",
            "billable_tokens",
        ):
            _require_non_negative_int(getattr(self, field), field)
        _require_money(self.list_cost, "list_cost")
        _require_money(self.billed_cost, "billed_cost")


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


class UnknownModelError(Exception):
    """Raised when a write references a model that is not registered."""

    def __init__(self, model_id: str) -> None:
        super().__init__(f"model '{model_id}' does not exist")
        self.model_id = model_id


class DuplicatePriceError(Exception):
    """Raised when two prices share a model and effective timestamp."""

    def __init__(self, model_id: str, effective_from: datetime) -> None:
        super().__init__(
            f"model '{model_id}' already has a price effective at {effective_from.isoformat()}"
        )
        self.model_id = model_id
        self.effective_from = effective_from


class DuplicateApiKeyError(Exception):
    def __init__(self) -> None:
        super().__init__("an API key with the same hash already exists")


@dataclass(frozen=True, slots=True)
class TenantLimitPatch:
    """Partial limit update; only fields with a true ``set_*`` flag are written."""

    monthly_token_quota: int | None = None
    requests_per_minute: int | None = None
    audit_enabled: bool | None = None
    plan_tokens: int | None = None
    plan_allow_overage: bool | None = None
    monthly_cost_budget: Decimal | None = None
    audit_retention_days: int | None = None
    set_monthly_token_quota: bool = False
    set_requests_per_minute: bool = False
    set_audit_enabled: bool = False
    set_plan_tokens: bool = False
    set_plan_allow_overage: bool = False
    set_monthly_cost_budget: bool = False
    set_audit_retention_days: bool = False


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

    async def get_model_access(self, tenant_id: UUID) -> ModelAccess | None: ...

    async def set_model_access(
        self,
        tenant_id: UUID,
        *,
        mode: ModelAccessMode,
        model_ids: Sequence[str],
    ) -> ModelAccess | None: ...


class UsageRepository(Protocol):
    async def record(self, record: UsageRecord) -> None: ...

    async def token_total(self, *, tenant_id: UUID, since: datetime, until: datetime) -> int: ...

    async def monthly_totals(
        self, *, tenant_id: UUID, since: datetime, until: datetime
    ) -> MonthlyUsage: ...

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


class ModelPriceRepository(Protocol):
    async def get_effective_price(self, *, model_id: str, at: datetime) -> ModelPrice | None: ...

    async def create_price(self, price: ModelPrice) -> ModelPrice: ...

    async def list_prices(
        self, *, model_id: str, limit: int, offset: int
    ) -> tuple[Sequence[ModelPrice], int]: ...


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
    trace_id: str | None = None

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

    async def delete_requests_before(
        self, *, tenant_id: UUID, cutoff: datetime, batch_size: int
    ) -> int:
        """Delete up to ``batch_size`` requests older than ``cutoff``; diffs cascade."""
        ...

    async def delete_orphan_sessions_before(
        self, *, tenant_id: UUID, cutoff: datetime, batch_size: int
    ) -> int:
        """Delete up to ``batch_size`` sessions last seen before ``cutoff`` with no requests."""
        ...

    async def count_requests(
        self,
        *,
        tenant_id: UUID,
        since: datetime | None,
        until: datetime | None,
    ) -> int: ...

    def iter_requests_for_export(
        self,
        *,
        tenant_id: UUID,
        since: datetime,
        until: datetime,
        batch_size: int,
    ) -> AsyncIterator[AuditRequestRecord]:
        """Stream requests in ``(created_at, request_id)`` order with keyset pagination."""
        ...


class AdminRole(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"
    AUDITOR = "auditor"


class AdminActorType(StrEnum):
    ADMIN = "admin"
    MASTER = "master"
    BOOTSTRAP = "bootstrap"


@dataclass(frozen=True, slots=True)
class AdminUser:
    """A human or service identity allowed to use the management API."""

    id: UUID
    username: str
    display_name: str
    role: AdminRole
    password_hash: str
    active: bool
    created_at: datetime
    updated_at: datetime
    password_changed_at: datetime
    last_login_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_non_blank(self.username, "username")
        _require_non_blank(self.display_name, "display_name")
        if not isinstance(self.role, AdminRole):
            raise ValueError("role must be an AdminRole")
        _require_non_blank(self.password_hash, "password_hash")
        if not isinstance(self.active, bool):
            raise ValueError("active must be a boolean")
        for field in ("created_at", "updated_at", "password_changed_at"):
            _require_aware(getattr(self, field), field)
        _require_optional_aware(self.last_login_at, "last_login_at")


@dataclass(frozen=True, slots=True)
class AdminSession:
    id: UUID
    admin_id: UUID
    token_hash: str
    csrf_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_uuid(self.admin_id, "admin_id")
        _require_key_hash(self.token_hash)
        _require_key_hash(self.csrf_hash)
        _require_aware(self.created_at, "created_at")
        _require_aware(self.expires_at, "expires_at")
        _require_optional_aware(self.revoked_at, "revoked_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now


@dataclass(frozen=True, slots=True)
class AdminAuditEvent:
    """One management action. Metadata only: never secrets or payload bodies."""

    id: UUID
    actor_type: AdminActorType
    actor_id: UUID | None
    actor_name: str
    action: str
    target_type: str
    target_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        if not isinstance(self.actor_type, AdminActorType):
            raise ValueError("actor_type must be an AdminActorType")
        _require_optional_uuid_value(self.actor_id, "actor_id")
        _require_non_blank(self.actor_name, "actor_name")
        _require_non_blank(self.action, "action")
        _require_non_blank(self.target_type, "target_type")
        _require_non_blank(self.target_id, "target_id")
        _require_aware(self.created_at, "created_at")


class DuplicateAdminError(Exception):
    def __init__(self, username: str) -> None:
        super().__init__(f"admin '{username}' already exists")
        self.username = username


class LastOwnerError(Exception):
    """Raised when an update would leave the system without an active owner."""

    def __init__(self) -> None:
        super().__init__("at least one active owner is required")


class AdminUserRepository(Protocol):
    async def create_admin(self, admin: AdminUser) -> AdminUser: ...

    async def get_admin(self, admin_id: UUID) -> AdminUser | None: ...

    async def get_admin_by_username(self, username: str) -> AdminUser | None: ...

    async def list_admins(self, *, limit: int, offset: int) -> tuple[Sequence[AdminUser], int]: ...

    async def update_admin(
        self,
        admin_id: UUID,
        *,
        role: AdminRole | None = None,
        active: bool | None = None,
        display_name: str | None = None,
        password_hash: str | None = None,
        password_changed_at: datetime | None = None,
        last_login_at: datetime | None = None,
        updated_at: datetime,
    ) -> AdminUser | None: ...

    async def count_active_owners(self) -> int: ...


class AdminSessionRepository(Protocol):
    async def create_session(self, admin_session: AdminSession) -> AdminSession: ...

    async def get_session_by_token_hash(self, token_hash: str) -> AdminSession | None: ...

    async def revoke_session(self, session_id: UUID, *, at: datetime) -> bool: ...

    async def revoke_sessions_for_admin(self, admin_id: UUID, *, at: datetime) -> int: ...


class AdminAuditRepository(Protocol):
    async def record(self, event: AdminAuditEvent) -> None: ...

    async def list_events(
        self,
        *,
        actor_id: UUID | None,
        action: str | None,
        target_type: str | None,
        target_id: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[AdminAuditEvent], int]: ...


class LoginThrottle(Protocol):
    async def hit(self, *, key: str, limit: int, window_seconds: int, now: datetime) -> bool:
        """Return True when the attempt is allowed."""
        ...

    async def clear(self, *, key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ModelDeployment:
    """One upstream route for a public model.

    ``credential_env`` is the *name* of an environment variable, never the secret.
    ``base_url`` overrides the provider default so the same provider can be used with
    several accounts or proxies.
    """

    id: UUID
    model_id: str
    name: str
    provider: ProviderName
    upstream_model: str
    weight: int
    enabled: bool
    created_at: datetime
    credential_env: str | None = None
    base_url: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_non_blank(self.model_id, "model_id")
        _require_non_blank(self.name, "name")
        _require_provider(self.provider, "provider")
        _require_non_blank(self.upstream_model, "upstream_model")
        if not isinstance(self.weight, int) or isinstance(self.weight, bool):
            raise ValueError("weight must be an integer")
        if self.weight < 1 or self.weight > 100:
            raise ValueError("weight must be between 1 and 100")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a boolean")
        _require_aware(self.created_at, "created_at")
        if self.credential_env is not None:
            _require_non_blank(self.credential_env, "credential_env")
            if not self.credential_env.replace("_", "").isalnum():
                raise ValueError("credential_env must be an environment variable name")
            if self.credential_env.upper() != self.credential_env:
                raise ValueError("credential_env must be uppercase")
        if self.base_url is not None:
            _require_non_blank(self.base_url, "base_url")
            if not self.base_url.startswith(("http://", "https://")):
                raise ValueError("base_url must be an http(s) URL")


class DuplicateDeploymentError(Exception):
    def __init__(self, model_id: str, name: str) -> None:
        super().__init__(f"model '{model_id}' already has a deployment named '{name}'")
        self.model_id = model_id
        self.name = name


class ModelDeploymentRepository(Protocol):
    async def list_deployments(self, model_id: str) -> Sequence[ModelDeployment]: ...

    async def get_deployment(self, deployment_id: UUID) -> ModelDeployment | None: ...

    async def create_deployment(self, deployment: ModelDeployment) -> ModelDeployment: ...

    async def update_deployment(
        self,
        deployment_id: UUID,
        *,
        name: str | None = None,
        upstream_model: str | None = None,
        weight: int | None = None,
        enabled: bool | None = None,
        credential_env: str | None = None,
        base_url: str | None = None,
        replace_credential_env: bool = False,
        replace_base_url: bool = False,
    ) -> ModelDeployment | None: ...

    async def delete_deployment(self, deployment_id: UUID) -> bool: ...
