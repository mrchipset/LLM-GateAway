from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from llm_gateway.providers.base import ProviderName


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Public model name plus the provider deployment that serves it."""

    id: str
    provider: ProviderName
    upstream_model: str
    created_at: datetime
    enabled: bool = True


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


class DuplicateModelError(Exception):
    def __init__(self, model_id: str) -> None:
        super().__init__(f"model '{model_id}' already exists")
        self.model_id = model_id


class DuplicateApiKeyError(Exception):
    def __init__(self) -> None:
        super().__init__("an API key with the same hash already exists")


class ModelRepository(Protocol):
    async def list_models(
        self, *, limit: int, offset: int
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


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: Sequence[T]
    total: int
    limit: int
    offset: int
