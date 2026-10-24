from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from llm_gateway.providers.base import ProviderName

_HEX_DIGITS = frozenset("0123456789abcdef")


def _require_non_blank(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be blank")


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _require_key_hash(value: str) -> None:
    if len(value) != 64 or any(char not in _HEX_DIGITS for char in value):
        raise ValueError("key_hash must be 64 lowercase hex characters")


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
    name: str
    key_hash: str
    key_prefix: str
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.name, "name")
        _require_key_hash(self.key_hash)
        _require_aware(self.created_at, "created_at")
        for field in ("expires_at", "revoked_at", "last_used_at"):
            value = getattr(self, field)
            if value is not None:
                _require_aware(value, field)


class DuplicateModelError(Exception):
    def __init__(self, model_id: str) -> None:
        super().__init__(f"model '{model_id}' already exists")
        self.model_id = model_id


class DuplicateApiKeyError(Exception):
    def __init__(self) -> None:
        super().__init__("an API key with the same hash already exists")


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

    async def list_keys(self, *, limit: int, offset: int) -> tuple[Sequence[ApiKeyRecord], int]: ...

    async def revoke_key(self, key_id: UUID, revoked_at: datetime) -> bool: ...

    async def touch_last_used(self, key_id: UUID, used_at: datetime) -> None: ...
