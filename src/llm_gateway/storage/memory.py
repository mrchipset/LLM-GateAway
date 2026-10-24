from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from llm_gateway.storage.repositories import (
    ApiKeyRecord,
    DuplicateApiKeyError,
    DuplicateModelError,
    ModelConfig,
)


def _validate_page(*, limit: int, offset: int) -> None:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")


class InMemoryModelRepository:
    """Process-local model registry.

    Intended for tests and single-process development only: state is lost on
    restart and is not shared between workers. A per-instance lock serializes
    mutations; reads rely on the single-threaded event loop.
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelConfig] = {}
        self._lock = asyncio.Lock()

    async def list_models(self, *, limit: int, offset: int) -> tuple[Sequence[ModelConfig], int]:
        _validate_page(limit=limit, offset=offset)
        ordered = sorted(
            self._models.values(),
            key=lambda model: (model.created_at, model.id),
            reverse=True,
        )
        return ordered[offset : offset + limit], len(ordered)

    async def get_model(self, model_id: str) -> ModelConfig | None:
        return self._models.get(model_id)

    async def create_model(self, model: ModelConfig) -> ModelConfig:
        async with self._lock:
            if model.id in self._models:
                raise DuplicateModelError(model.id)
            self._models[model.id] = model
            return model

    async def delete_model(self, model_id: str) -> bool:
        async with self._lock:
            return self._models.pop(model_id, None) is not None


class InMemoryApiKeyRepository:
    """Process-local API key store with the same caveats as the model store."""

    def __init__(self) -> None:
        self._keys: dict[UUID, ApiKeyRecord] = {}
        self._ids_by_hash: dict[str, UUID] = {}
        self._lock = asyncio.Lock()

    async def create_key(self, record: ApiKeyRecord) -> ApiKeyRecord:
        async with self._lock:
            if record.key_hash in self._ids_by_hash:
                raise DuplicateApiKeyError()
            self._keys[record.id] = record
            self._ids_by_hash[record.key_hash] = record.id
            return record

    async def get_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        key_id = self._ids_by_hash.get(key_hash)
        if key_id is None:
            return None
        return self._keys.get(key_id)

    async def get_key(self, key_id: UUID) -> ApiKeyRecord | None:
        return self._keys.get(key_id)

    async def list_keys(self, *, limit: int, offset: int) -> tuple[Sequence[ApiKeyRecord], int]:
        _validate_page(limit=limit, offset=offset)
        ordered = sorted(
            self._keys.values(),
            key=lambda record: (record.created_at, str(record.id)),
            reverse=True,
        )
        return ordered[offset : offset + limit], len(ordered)

    async def revoke_key(self, key_id: UUID, revoked_at: datetime) -> bool:
        async with self._lock:
            record = self._keys.get(key_id)
            if record is None or record.revoked_at is not None:
                return False
            self._keys[key_id] = replace(record, revoked_at=revoked_at)
            return True

    async def touch_last_used(self, key_id: UUID, used_at: datetime) -> None:
        async with self._lock:
            record = self._keys.get(key_id)
            if record is None:
                raise KeyError(f"api key {key_id} not found")
            self._keys[key_id] = replace(record, last_used_at=used_at)
