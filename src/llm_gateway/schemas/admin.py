from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llm_gateway.providers.base import ProviderName


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


class CreateTenantRequest(BaseModel):
    """Body for `POST /api/v1/tenants`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class TenantDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    name: str
    created_at: datetime


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
