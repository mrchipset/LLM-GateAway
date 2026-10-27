from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from llm_gateway.storage.repositories import (
    ApiKeyRecord,
    AuditPrefixRecord,
    AuditRequestRecord,
    AuditRequestSummary,
    AuditSessionFilters,
    AuditSessionPage,
    AuditSessionRecord,
    AuditTurnDiffRecord,
    DuplicateApiKeyError,
    DuplicateModelError,
    DuplicateTenantError,
    KeyUsage,
    ModelConfig,
    ModelUsage,
    Tenant,
    TenantLimitPatch,
    TimeBucket,
    UsagePoint,
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
            if patch.set_audit_enabled and patch.audit_enabled is not None:
                changes["audit_enabled"] = patch.audit_enabled
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

    async def get_keys(self, key_ids: Sequence[UUID]) -> Sequence[ApiKeyRecord]:
        return [self._keys[key_id] for key_id in key_ids if key_id in self._keys]

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


def _validate_optional_window(*, since: datetime | None, until: datetime | None) -> None:
    for field, value in (("since", since), ("until", until)):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError(f"{field} must be timezone-aware")
    if since is not None and until is not None and since >= until:
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
        _validate_optional_window(since=since, until=until)
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

    async def summary_by_key(
        self,
        *,
        tenant_id: UUID | None,
        model_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Sequence[KeyUsage]:
        _validate_optional_window(since=since, until=until)
        records = self._select(tenant_id=tenant_id, model_id=model_id, since=since, until=until)
        aggregated: dict[UUID, KeyUsage] = {}
        for record in records:
            current = aggregated.get(record.api_key_id)
            if current is None:
                aggregated[record.api_key_id] = KeyUsage(
                    api_key_id=record.api_key_id,
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    cached_tokens=record.cached_tokens,
                    total_tokens=record.total_tokens,
                    requests=1,
                )
                continue
            aggregated[record.api_key_id] = KeyUsage(
                api_key_id=current.api_key_id,
                prompt_tokens=current.prompt_tokens + record.prompt_tokens,
                completion_tokens=current.completion_tokens + record.completion_tokens,
                cached_tokens=current.cached_tokens + record.cached_tokens,
                total_tokens=current.total_tokens + record.total_tokens,
                requests=current.requests + 1,
            )
        return sorted(
            aggregated.values(),
            key=lambda item: (-item.total_tokens, item.api_key_id),
        )

    async def summary_series(
        self,
        *,
        tenant_id: UUID | None,
        model_id: str | None,
        since: datetime | None,
        until: datetime | None,
        bucket: TimeBucket,
    ) -> Sequence[UsagePoint]:
        _validate_optional_window(since=since, until=until)
        records = self._select(tenant_id=tenant_id, model_id=model_id, since=since, until=until)
        aggregated: dict[datetime, UsagePoint] = {}
        for record in records:
            bucket_start = _bucket_start(record.created_at, bucket)
            current = aggregated.get(bucket_start)
            if current is None:
                aggregated[bucket_start] = UsagePoint(
                    bucket_start=bucket_start,
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    cached_tokens=record.cached_tokens,
                    total_tokens=record.total_tokens,
                    requests=1,
                )
                continue
            aggregated[bucket_start] = UsagePoint(
                bucket_start=bucket_start,
                prompt_tokens=current.prompt_tokens + record.prompt_tokens,
                completion_tokens=current.completion_tokens + record.completion_tokens,
                cached_tokens=current.cached_tokens + record.cached_tokens,
                total_tokens=current.total_tokens + record.total_tokens,
                requests=current.requests + 1,
            )
        return sorted(aggregated.values(), key=lambda item: item.bucket_start)


def _bucket_start(created_at: datetime, bucket: TimeBucket) -> datetime:
    utc = created_at.astimezone(UTC)
    if bucket is TimeBucket.HOUR:
        return utc.replace(minute=0, second=0, microsecond=0)
    return utc.replace(hour=0, minute=0, second=0, microsecond=0)


class InMemoryAuditRepository:
    """Process-local request audit store with the same caveats as the others."""

    def __init__(self) -> None:
        self._sessions: dict[UUID, AuditSessionRecord] = {}
        self._external_ids: dict[tuple[UUID, str], UUID] = {}
        self._requests: dict[str, AuditRequestRecord] = {}
        self._diffs: dict[str, AuditTurnDiffRecord] = {}
        self._lock = asyncio.Lock()

    async def record_turn(
        self,
        *,
        session: AuditSessionRecord,
        request: AuditRequestRecord,
        diff: AuditTurnDiffRecord | None,
    ) -> None:
        async with self._lock:
            existing = self._sessions.get(session.id)
            if existing is None:
                if session.external_session_id is not None:
                    key = (session.tenant_id, session.external_session_id)
                    if key in self._external_ids:
                        raise ValueError("external session id already exists for this tenant")
                    self._external_ids[key] = session.id
                self._sessions[session.id] = session
            else:
                changes: dict[str, object] = {
                    "request_count": existing.request_count + 1,
                    "total_tokens": existing.total_tokens + (request.total_tokens or 0),
                    "last_seen_at": max(existing.last_seen_at, request.created_at),
                }
                if existing.request_count == 0:
                    changes.update(
                        {
                            "root_request_id": session.root_request_id,
                            "model_id": session.model_id,
                            "provider": session.provider,
                            "title_preview": session.title_preview,
                            "created_at": session.created_at,
                        }
                    )
                self._sessions[session.id] = replace(existing, **changes)  # pyright: ignore[reportArgumentType]
            self._requests[request.request_id] = request
            if diff is not None:
                self._diffs[diff.request_id] = diff

    async def get_session_by_external_id(
        self, *, tenant_id: UUID, external_session_id: str
    ) -> AuditSessionRecord | None:
        session_id = self._external_ids.get((tenant_id, external_session_id))
        if session_id is None:
            return None
        return self._sessions.get(session_id)

    async def ensure_session(self, *, session: AuditSessionRecord) -> AuditSessionRecord:
        async with self._lock:
            existing = self._sessions.get(session.id)
            if existing is not None:
                return existing
            if session.external_session_id is not None:
                key = (session.tenant_id, session.external_session_id)
                existing_id = self._external_ids.get(key)
                if existing_id is not None:
                    return self._sessions[existing_id]
                self._external_ids[key] = session.id
            self._sessions[session.id] = session
            return session

    async def get_latest_request(self, *, session_id: UUID) -> AuditRequestRecord | None:
        candidates = [
            request for request in self._requests.values() if request.session_id == session_id
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (item.turn_index, item.created_at, item.request_id),
        )

    async def recent_prefix_requests(
        self, *, tenant_id: UUID, api_key_id: UUID, since: datetime, limit: int
    ) -> list[AuditPrefixRecord]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        candidates = [
            AuditPrefixRecord(
                request_id=request.request_id,
                session_id=request.session_id,
                turn_index=request.turn_index,
                message_hashes=request.message_hashes,
                created_at=request.created_at,
            )
            for request in self._requests.values()
            if request.tenant_id == tenant_id
            and request.api_key_id == api_key_id
            and request.created_at >= since
        ]
        ordered = sorted(
            candidates,
            key=lambda item: (item.created_at, item.request_id),
            reverse=True,
        )
        return ordered[:limit]

    async def list_sessions(
        self, *, filters: AuditSessionFilters, limit: int, offset: int
    ) -> AuditSessionPage:
        _validate_page(limit=limit, offset=offset)
        matched = [
            session
            for session in self._sessions.values()
            if session.request_count > 0
            and _audit_session_matches(session, filters, self._requests)
        ]
        ordered = sorted(
            matched,
            key=lambda item: (item.last_seen_at, str(item.id)),
            reverse=True,
        )
        return AuditSessionPage(
            items=ordered[offset : offset + limit],
            total=len(ordered),
        )

    async def get_session(self, *, session_id: UUID) -> AuditSessionRecord | None:
        return self._sessions.get(session_id)

    async def list_session_requests(self, *, session_id: UUID) -> list[AuditRequestRecord]:
        candidates = [
            request for request in self._requests.values() if request.session_id == session_id
        ]
        return sorted(
            candidates,
            key=lambda item: (item.turn_index, item.created_at, item.request_id),
        )

    async def list_session_request_summaries(
        self, *, session_id: UUID
    ) -> list[AuditRequestSummary]:
        requests = await self.list_session_requests(session_id=session_id)
        return [
            AuditRequestSummary(
                request_id=request.request_id,
                session_id=request.session_id,
                parent_request_id=request.parent_request_id,
                tenant_id=request.tenant_id,
                api_key_id=request.api_key_id,
                turn_index=request.turn_index,
                match_method=request.match_method,
                change_type=request.change_type,
                model_id=request.model_id,
                provider=request.provider,
                is_stream=request.is_stream,
                finish_reason=request.finish_reason,
                status=request.status,
                prompt_tokens=request.prompt_tokens,
                completion_tokens=request.completion_tokens,
                cached_tokens=request.cached_tokens,
                total_tokens=request.total_tokens,
                truncated=request.truncated,
                created_at=request.created_at,
                request_message_count=len(request.request_messages),
            )
            for request in requests
        ]

    async def get_diffs(self, *, request_ids: Sequence[str]) -> dict[str, AuditTurnDiffRecord]:
        return {
            request_id: self._diffs[request_id]
            for request_id in request_ids
            if request_id in self._diffs
        }

    async def get_request(self, *, request_id: str) -> AuditRequestRecord | None:
        return self._requests.get(request_id)

    async def get_diff(self, *, request_id: str) -> AuditTurnDiffRecord | None:
        return self._diffs.get(request_id)


def _audit_session_matches(
    session: AuditSessionRecord,
    filters: AuditSessionFilters,
    requests: dict[str, AuditRequestRecord],
) -> bool:
    if filters.tenant_id is not None and session.tenant_id != filters.tenant_id:
        return False
    if filters.api_key_id is not None and session.api_key_id != filters.api_key_id:
        return False
    if filters.model_id is not None and session.model_id != filters.model_id:
        return False
    if filters.since is not None and session.last_seen_at < filters.since:
        return False
    if filters.until is not None and session.last_seen_at >= filters.until:
        return False
    if filters.q is not None:
        query = filters.q
        request_id_matches = any(
            request.session_id == session.id and request.request_id.startswith(query)
            for request in requests.values()
        )
        if not (
            str(session.id).startswith(query)
            or session.root_request_id.startswith(query)
            or request_id_matches
            or query.lower() in session.title_preview.lower()
        ):
            return False
    return True
