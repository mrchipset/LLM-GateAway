from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
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


@dataclass(frozen=True, slots=True)
class Tenant:
    """An organizational label that owns API keys."""

    id: UUID
    name: str
    created_at: datetime
    monthly_token_quota: int | None = None
    requests_per_minute: int | None = None

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
    set_monthly_token_quota: bool = False
    set_requests_per_minute: bool = False


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
