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
    DuplicateTenantError,
    ModelConfig,
    ModelUsage,
    Tenant,
    TenantLimitPatch,
    UsageRecord,
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

    async def list_models(
        self, *, limit: int, offset: int, enabled_only: bool = False
    ) -> tuple[Sequence[ModelConfig], int]:
        _validate_page(limit=limit, offset=offset)
        models: list[ModelConfig] = list(self._models.values())
        if enabled_only:
            models = [model for model in models if model.enabled]
        ordered = sorted(
            models,
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


class InMemoryTenantRepository:
    """Process-local tenant registry with the same caveats as the model store."""

    def __init__(self) -> None:
        self._tenants: dict[UUID, Tenant] = {}
        self._lock = asyncio.Lock()

    async def create_tenant(self, tenant: Tenant) -> Tenant:
        async with self._lock:
            if tenant.id in self._tenants:
                raise DuplicateTenantError(tenant.name)
            if any(existing.name == tenant.name for existing in self._tenants.values()):
                raise DuplicateTenantError(tenant.name)
            self._tenants[tenant.id] = tenant
            return tenant

    async def get_tenant(self, tenant_id: UUID) -> Tenant | None:
        return self._tenants.get(tenant_id)

    async def list_tenants(self, *, limit: int, offset: int) -> tuple[Sequence[Tenant], int]:
        _validate_page(limit=limit, offset=offset)
        ordered = sorted(
            self._tenants.values(),
            key=lambda tenant: (tenant.created_at, tenant.id),
            reverse=True,
        )
        return ordered[offset : offset + limit], len(ordered)

    async def set_tenant_limits(
        self,
        tenant_id: UUID,
        *,
        patch: TenantLimitPatch,
    ) -> Tenant | None:
        async with self._lock:
            tenant = self._tenants.get(tenant_id)
            if tenant is None:
                return None
            changes: dict[str, object] = {}
            if patch.set_monthly_token_quota:
                changes["monthly_token_quota"] = patch.monthly_token_quota
            if patch.set_requests_per_minute:
                changes["requests_per_minute"] = patch.requests_per_minute
            if not changes:
                return tenant
            updated = replace(tenant, **changes)  # pyright: ignore[reportArgumentType]
            self._tenants[tenant_id] = updated
            return updated


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

    async def list_keys(
        self, *, limit: int, offset: int, tenant_id: UUID | None = None
    ) -> tuple[Sequence[ApiKeyRecord], int]:
        _validate_page(limit=limit, offset=offset)
        records: list[ApiKeyRecord] = list(self._keys.values())
        if tenant_id is not None:
            records = [record for record in records if record.tenant_id == tenant_id]
        ordered = sorted(
            records,
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


def _validate_token_window(*, since: datetime, until: datetime) -> None:
    for field, value in (("since", since), ("until", until)):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must be timezone-aware")
    if since >= until:
        raise ValueError("since must be before until")


def _usage_matches(
    record: UsageRecord,
    *,
    tenant_id: UUID | None,
    model_id: str | None,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    if tenant_id is not None and record.tenant_id != tenant_id:
        return False
    if model_id is not None and record.model_id != model_id:
        return False
    if since is not None and record.created_at < since:
        return False
    return not (until is not None and record.created_at >= until)


class InMemoryUsageRepository:
    """Process-local usage ledger with the same caveats as the other stores."""

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []
        self._lock = asyncio.Lock()

    async def record(self, record: UsageRecord) -> None:
        async with self._lock:
            self._records.append(record)

    async def token_total(self, *, tenant_id: UUID, since: datetime, until: datetime) -> int:
        _validate_token_window(since=since, until=until)
        return sum(
            record.total_tokens
            for record in self._records
            if record.tenant_id == tenant_id
            and record.created_at >= since
            and record.created_at < until
        )

    def _select(
        self,
        *,
        tenant_id: UUID | None,
        model_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> list[UsageRecord]:
        return [
            record
            for record in self._records
            if _usage_matches(
                record,
                tenant_id=tenant_id,
                model_id=model_id,
                since=since,
                until=until,
            )
        ]

    async def summary_by_model(
        self,
        *,
        tenant_id: UUID | None,
        model_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Sequence[ModelUsage]:
        records = self._select(tenant_id=tenant_id, model_id=model_id, since=since, until=until)
        aggregated: dict[tuple[str, str], ModelUsage] = {}
        for record in records:
            key = (record.model_id, record.provider.value)
            current = aggregated.get(key)
            if current is None:
                aggregated[key] = ModelUsage(
                    model_id=record.model_id,
                    provider=record.provider,
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    cached_tokens=record.cached_tokens,
                    total_tokens=record.total_tokens,
                    requests=1,
                )
                continue
            aggregated[key] = ModelUsage(
                model_id=current.model_id,
                provider=current.provider,
                prompt_tokens=current.prompt_tokens + record.prompt_tokens,
                completion_tokens=current.completion_tokens + record.completion_tokens,
                cached_tokens=current.cached_tokens + record.cached_tokens,
                total_tokens=current.total_tokens + record.total_tokens,
                requests=current.requests + 1,
            )
        return sorted(
            aggregated.values(),
            key=lambda item: (-item.total_tokens, item.model_id),
        )
