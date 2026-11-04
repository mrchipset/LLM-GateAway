from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llm_gateway.providers.base import ProviderName
from llm_gateway.storage.repositories import AdminActorType, AdminRole, ModelAccessMode


class CreateApiKeyRequest(BaseModel):
    """Body for `POST /api/v1/keys`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    tenant_id: UUID
    expires_at: datetime | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("expires_at")
    @classmethod
    def _require_aware_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("expires_at must be timezone-aware")
        return value


class CreatedApiKeyResponse(BaseModel):
    """Response for `POST /api/v1/keys`; contains the plaintext key exactly once."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    tenant_id: UUID
    name: str
    key: str
    key_prefix: str
    created_at: datetime
    expires_at: datetime | None = None


class ApiKeySummary(BaseModel):
    """Key metadata safe to return from the management API; never the secret."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    tenant_id: UUID
    name: str
    key_prefix: str
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class ApiKeyListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ApiKeySummary]
    total: int
    limit: int
    offset: int
    tenant_id: UUID | None = None


class CreateTenantRequest(BaseModel):
    """Body for `POST /api/v1/tenants`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    monthly_token_quota: int | None = Field(default=None, ge=1)
    requests_per_minute: int | None = Field(default=None, ge=1)
    audit_enabled: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class UpdateTenantLimitsRequest(BaseModel):
    """Body for `PATCH /api/v1/tenants/{tenant_id}`.

    Omitted fields mean "unchanged"; an explicit null clears the limit.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    monthly_token_quota: int | None = Field(default=None, ge=1)
    requests_per_minute: int | None = Field(default=None, ge=1)
    audit_enabled: bool | None = None
    plan_tokens: int | None = Field(default=None, ge=1)
    plan_allow_overage: bool | None = None
    monthly_cost_budget: Decimal | None = Field(default=None, ge=0)


class TenantDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

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


class TenantBillingResponse(BaseModel):
    """Current-period billing state for one tenant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: UUID
    currency: str
    period_start: datetime
    period_end: datetime
    plan_tokens: int | None = None
    plan_allow_overage: bool = False
    monthly_cost_budget: Decimal | None = None
    used_tokens: int
    covered_tokens: int
    billable_tokens: int
    requests: int
    list_cost: Decimal
    billed_cost: Decimal
    budget_remaining: Decimal | None = None


class CreateModelPriceRequest(BaseModel):
    """Body for `POST /api/v1/models/{model_id}/prices`.

    Prices are per million tokens; ``cached_input_per_million`` falls back to the
    input price when omitted. A new row is appended, so history stays repriced-free.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_per_million: Decimal = Field(ge=0)
    cached_input_per_million: Decimal | None = Field(default=None, ge=0)
    output_per_million: Decimal = Field(ge=0)
    effective_from: datetime | None = None


class ModelPriceDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    model_id: str
    input_per_million: Decimal
    cached_input_per_million: Decimal | None = None
    output_per_million: Decimal
    currency: str
    effective_from: datetime
    created_at: datetime


class ModelPriceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ModelPriceDetail]
    total: int
    limit: int
    offset: int


class ModelAccessResponse(BaseModel):
    """Resolved model permissions for one tenant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: UUID
    mode: ModelAccessMode
    model_ids: list[str] = Field(default_factory=list)


class UpdateModelAccessRequest(BaseModel):
    """Body for `PUT /api/v1/tenants/{tenant_id}/model-access`.

    Replaces the whole permission set. ``mode=allowlist`` with an empty list
    deliberately blocks every model for that tenant.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: ModelAccessMode
    model_ids: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("model_ids")
    @classmethod
    def _validate_model_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for model_id in value:
            stripped = model_id.strip()
            if not stripped:
                raise ValueError("model_ids must not contain blank values")
            if len(stripped) > 128:
                raise ValueError("model_ids entries must be at most 128 characters")
            normalized.append(stripped)
        return normalized


class TenantListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[TenantDetail]
    total: int
    limit: int
    offset: int


class CreateModelRequest(BaseModel):
    """Body for `POST /api/v1/models`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    provider: ProviderName
    upstream_model: str = Field(min_length=1, max_length=256)
    enabled: bool = True

    @field_validator("upstream_model", mode="before")
    @classmethod
    def _strip_upstream_model(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ModelDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    provider: ProviderName
    upstream_model: str
    enabled: bool
    created_at: datetime


class ModelListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ModelDetail]
    total: int
    limit: int
    offset: int


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str
    display_name: str
    role: AdminRole
    actor_type: AdminActorType
    expires_at: datetime


class CurrentAdminResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_type: AdminActorType
    name: str
    role: AdminRole
    admin_id: UUID | None = None
    session_expires_at: datetime | None = None


class CreateAdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9._-]+$",
    )
    display_name: str = Field(min_length=1, max_length=100)
    role: AdminRole
    password: str = Field(min_length=12, max_length=256)


class UpdateAdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: AdminRole | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)


class AdminDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    username: str
    display_name: str
    role: AdminRole
    active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None


class AdminListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[AdminDetail]
    total: int
    limit: int
    offset: int


class AdminAuditEventDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    actor_type: AdminActorType
    actor_id: UUID | None = None
    actor_name: str
    action: str
    target_type: str
    target_id: str
    before: dict[str, object] | None = None
    after: dict[str, object] | None = None
    request_id: str | None = None
    created_at: datetime


class AdminAuditListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[AdminAuditEventDetail]
    total: int
    limit: int
    offset: int
