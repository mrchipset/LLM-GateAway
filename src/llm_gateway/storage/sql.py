from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import String, delete, func, literal, or_, select, text, update
from sqlalchemy import cast as sa_cast
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from llm_gateway.providers.base import ProviderName
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
    UnknownTenantError,
    UsagePoint,
    UsageRecord,
)
from llm_gateway.storage.tables import (
    ApiKeyRow,
    AuditRequestRow,
    AuditSessionRow,
    AuditTurnDiffRow,
    ModelRow,
    TenantRow,
    UsageRow,
)

_UNIQUE_VIOLATION_SQLSTATE = "23505"
_FOREIGN_KEY_VIOLATION_SQLSTATE = "23503"


def _validate_page(*, limit: int, offset: int) -> None:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")


def _is_unique_violation(error: IntegrityError) -> bool:
    original = error.orig
    return (
        getattr(original, "sqlstate", None) == _UNIQUE_VIOLATION_SQLSTATE
        or getattr(original, "pgcode", None) == _UNIQUE_VIOLATION_SQLSTATE
    )


def _is_foreign_key_violation(error: IntegrityError) -> bool:
    original = error.orig
    return (
        getattr(original, "sqlstate", None) == _FOREIGN_KEY_VIOLATION_SQLSTATE
        or getattr(original, "pgcode", None) == _FOREIGN_KEY_VIOLATION_SQLSTATE
    )


def _is_tenant_foreign_key_violation(error: IntegrityError) -> bool:
    original = error.orig
    constraint = getattr(original, "constraint_name", None)
    if constraint is not None:
        return constraint == "fk_usage_records_tenant_id"
    return "fk_usage_records_tenant_id" in str(original)


def _validate_optional_window(*, since: datetime | None, until: datetime | None) -> None:
    for field, value in (("since", since), ("until", until)):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError(f"{field} must be timezone-aware")
    if since is not None and until is not None and since >= until:
        raise ValueError("since must be before until")


def _usage_filters(
    *,
    tenant_id: UUID | None,
    model_id: str | None,
    since: datetime | None,
    until: datetime | None,
) -> tuple[ColumnElement[bool], ...]:
    filters: list[ColumnElement[bool]] = []
    if tenant_id is not None:
        filters.append(UsageRow.tenant_id == tenant_id)
    if model_id is not None:
        filters.append(UsageRow.model_id == model_id)
    if since is not None:
        filters.append(UsageRow.created_at >= since)
    if until is not None:
        filters.append(UsageRow.created_at < until)
    return tuple(filters)


def _to_model(row: ModelRow) -> ModelConfig:
    try:
        provider = ProviderName(row.provider)
    except ValueError as exc:
        raise ValueError(f"stored model '{row.id}' has unknown provider {row.provider!r}") from exc
    return ModelConfig(
        id=row.id,
        provider=provider,
        upstream_model=row.upstream_model,
        created_at=row.created_at,
        enabled=row.enabled,
    )


def _to_tenant(row: TenantRow) -> Tenant:
    return Tenant(
        id=row.id,
        name=row.name,
        created_at=row.created_at,
        monthly_token_quota=row.monthly_token_quota,
        requests_per_minute=row.requests_per_minute,
        audit_enabled=row.audit_enabled,
    )


def _validate_token_window(*, since: datetime, until: datetime) -> None:
    for field, value in (("since", since), ("until", until)):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must be timezone-aware")
    if since >= until:
        raise ValueError("since must be before until")


def _to_key(row: ApiKeyRow) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        key_hash=row.key_hash,
        key_prefix=row.key_prefix,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        last_used_at=row.last_used_at,
    )


class SqlAlchemyModelRepository:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_models(
        self, *, limit: int, offset: int, enabled_only: bool = False
    ) -> tuple[Sequence[ModelConfig], int]:
        _validate_page(limit=limit, offset=offset)
        filters = (ModelRow.enabled.is_(True),) if enabled_only else ()
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.scalars(
                    select(ModelRow)
                    .where(*filters)
                    .order_by(ModelRow.created_at.desc(), ModelRow.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            total = await session.scalar(select(func.count()).select_from(ModelRow).where(*filters))
            models = [_to_model(row) for row in rows]
        return models, total or 0

    async def get_model(self, model_id: str) -> ModelConfig | None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(ModelRow, model_id)
            return _to_model(row) if row is not None else None

    async def create_model(self, model: ModelConfig) -> ModelConfig:
        row = ModelRow(
            id=model.id,
            provider=model.provider.value,
            upstream_model=model.upstream_model,
            enabled=model.enabled,
            created_at=model.created_at,
        )
        try:
            async with self._session_factory() as session, session.begin():
                session.add(row)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                raise DuplicateModelError(model.id) from exc
            raise
        return model

    async def delete_model(self, model_id: str) -> bool:
        async with self._session_factory() as session, session.begin():
            result = cast(
                "CursorResult[tuple[()]]",
                await session.execute(delete(ModelRow).where(ModelRow.id == model_id)),
            )
            return result.rowcount == 1


class SqlAlchemyTenantRepository:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_tenant(self, tenant: Tenant) -> Tenant:
        row = TenantRow(
            id=tenant.id,
            name=tenant.name,
            created_at=tenant.created_at,
            monthly_token_quota=tenant.monthly_token_quota,
            requests_per_minute=tenant.requests_per_minute,
            audit_enabled=tenant.audit_enabled,
        )
        try:
            async with self._session_factory() as session, session.begin():
                session.add(row)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                raise DuplicateTenantError(tenant.name) from exc
            raise
        return tenant

    async def get_tenant(self, tenant_id: UUID) -> Tenant | None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(TenantRow, tenant_id)
            return _to_tenant(row) if row is not None else None

    async def list_tenants(self, *, limit: int, offset: int) -> tuple[Sequence[Tenant], int]:
        _validate_page(limit=limit, offset=offset)
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.scalars(
                    select(TenantRow)
                    .order_by(TenantRow.created_at.desc(), TenantRow.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            total = await session.scalar(select(func.count()).select_from(TenantRow))
            tenants = [_to_tenant(row) for row in rows]
        return tenants, total or 0

    async def set_tenant_limits(
        self,
        tenant_id: UUID,
        *,
        patch: TenantLimitPatch,
    ) -> Tenant | None:
        values: dict[str, int | bool | None] = {}
        if patch.set_monthly_token_quota:
            values["monthly_token_quota"] = patch.monthly_token_quota
        if patch.set_requests_per_minute:
            values["requests_per_minute"] = patch.requests_per_minute
        if patch.set_audit_enabled and patch.audit_enabled is not None:
            values["audit_enabled"] = patch.audit_enabled
        async with self._session_factory() as session, session.begin():
            if not values:
                row = await session.get(TenantRow, tenant_id)
            else:
                statement = (
                    update(TenantRow)
                    .where(TenantRow.id == tenant_id)
                    .values(**values)
                    .returning(TenantRow)
                )
                row = await session.scalar(statement)
            return _to_tenant(row) if row is not None else None


class SqlAlchemyApiKeyRepository:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_key(self, record: ApiKeyRecord) -> ApiKeyRecord:
        row = ApiKeyRow(
            id=record.id,
            tenant_id=record.tenant_id,
            name=record.name,
            key_hash=record.key_hash,
            key_prefix=record.key_prefix,
            created_at=record.created_at,
            expires_at=record.expires_at,
            revoked_at=record.revoked_at,
            last_used_at=record.last_used_at,
        )
        try:
            async with self._session_factory() as session, session.begin():
                session.add(row)
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                raise DuplicateApiKeyError() from exc
            if _is_foreign_key_violation(exc):
                raise UnknownTenantError(record.tenant_id) from exc
            raise
        return record

    async def get_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(select(ApiKeyRow).where(ApiKeyRow.key_hash == key_hash))
            return _to_key(row) if row is not None else None

    async def get_key(self, key_id: UUID) -> ApiKeyRecord | None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(ApiKeyRow, key_id)
            return _to_key(row) if row is not None else None

    async def get_keys(self, key_ids: Sequence[UUID]) -> Sequence[ApiKeyRecord]:
        if not key_ids:
            return []
        async with self._session_factory() as session, session.begin():
            rows = (await session.scalars(select(ApiKeyRow).where(ApiKeyRow.id.in_(key_ids)))).all()
            return [_to_key(row) for row in rows]

    async def list_keys(
        self, *, limit: int, offset: int, tenant_id: UUID | None = None
    ) -> tuple[Sequence[ApiKeyRecord], int]:
        _validate_page(limit=limit, offset=offset)
        filters = (ApiKeyRow.tenant_id == tenant_id,) if tenant_id is not None else ()
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.scalars(
                    select(ApiKeyRow)
                    .where(*filters)
                    .order_by(ApiKeyRow.created_at.desc(), ApiKeyRow.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            total = await session.scalar(
                select(func.count()).select_from(ApiKeyRow).where(*filters)
            )
            keys = [_to_key(row) for row in rows]
        return keys, total or 0

    async def revoke_key(self, key_id: UUID, revoked_at: datetime) -> bool:
        async with self._session_factory() as session, session.begin():
            result = cast(
                "CursorResult[tuple[()]]",
                await session.execute(
                    update(ApiKeyRow)
                    .where(ApiKeyRow.id == key_id, ApiKeyRow.revoked_at.is_(None))
                    .values(revoked_at=revoked_at)
                ),
            )
            return result.rowcount == 1

    async def touch_last_used(self, key_id: UUID, used_at: datetime) -> None:
        async with self._session_factory() as session, session.begin():
            result = cast(
                "CursorResult[tuple[()]]",
                await session.execute(
                    update(ApiKeyRow).where(ApiKeyRow.id == key_id).values(last_used_at=used_at)
                ),
            )
            if result.rowcount == 0:
                raise KeyError(f"api key {key_id} not found")


class SqlAlchemyUsageRepository:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, record: UsageRecord) -> None:
        row = UsageRow(
            id=record.id,
            request_id=record.request_id,
            tenant_id=record.tenant_id,
            api_key_id=record.api_key_id,
            model_id=record.model_id,
            provider=record.provider.value,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            total_tokens=record.total_tokens,
            cached_tokens=record.cached_tokens,
            created_at=record.created_at,
        )
        try:
            async with self._session_factory() as session, session.begin():
                session.add(row)
        except IntegrityError as exc:
            if _is_foreign_key_violation(exc) and _is_tenant_foreign_key_violation(exc):
                raise UnknownTenantError(record.tenant_id) from exc
            raise

    async def token_total(self, *, tenant_id: UUID, since: datetime, until: datetime) -> int:
        _validate_token_window(since=since, until=until)
        statement = select(func.coalesce(func.sum(UsageRow.total_tokens), 0)).where(
            UsageRow.tenant_id == tenant_id,
            UsageRow.created_at >= since,
            UsageRow.created_at < until,
        )
        async with self._session_factory() as session, session.begin():
            total = await session.scalar(statement)
        return int(total or 0)

    async def summary_by_model(
        self,
        *,
        tenant_id: UUID | None,
        model_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Sequence[ModelUsage]:
        _validate_optional_window(since=since, until=until)
        filters = _usage_filters(tenant_id=tenant_id, model_id=model_id, since=since, until=until)
        total_tokens = func.sum(UsageRow.total_tokens)
        statement = (
            select(
                UsageRow.model_id,
                UsageRow.provider,
                func.coalesce(func.sum(UsageRow.prompt_tokens), 0),
                func.coalesce(func.sum(UsageRow.completion_tokens), 0),
                func.coalesce(func.sum(UsageRow.cached_tokens), 0),
                func.coalesce(total_tokens, 0),
                func.count(),
            )
            .where(*filters)
            .group_by(UsageRow.model_id, UsageRow.provider)
            .order_by(total_tokens.desc(), UsageRow.model_id.asc())
        )
        async with self._session_factory() as session, session.begin():
            rows = (await session.execute(statement)).all()
        return [
            ModelUsage(
                model_id=row[0],
                provider=_parse_provider(row[1]),
                prompt_tokens=int(row[2]),
                completion_tokens=int(row[3]),
                cached_tokens=int(row[4]),
                total_tokens=int(row[5]),
                requests=int(row[6]),
            )
            for row in rows
        ]

    async def summary_by_key(
        self,
        *,
        tenant_id: UUID | None,
        model_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Sequence[KeyUsage]:
        _validate_optional_window(since=since, until=until)
        filters = _usage_filters(tenant_id=tenant_id, model_id=model_id, since=since, until=until)
        total_tokens = func.sum(UsageRow.total_tokens)
        statement = (
            select(
                UsageRow.api_key_id,
                func.coalesce(func.sum(UsageRow.prompt_tokens), 0),
                func.coalesce(func.sum(UsageRow.completion_tokens), 0),
                func.coalesce(func.sum(UsageRow.cached_tokens), 0),
                func.coalesce(total_tokens, 0),
                func.count(),
            )
            .where(*filters)
            .group_by(UsageRow.api_key_id)
            .order_by(total_tokens.desc(), UsageRow.api_key_id.asc())
        )
        async with self._session_factory() as session, session.begin():
            rows = (await session.execute(statement)).all()
        return [
            KeyUsage(
                api_key_id=row[0],
                prompt_tokens=int(row[1]),
                completion_tokens=int(row[2]),
                cached_tokens=int(row[3]),
                total_tokens=int(row[4]),
                requests=int(row[5]),
            )
            for row in rows
        ]

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
        filters = _usage_filters(tenant_id=tenant_id, model_id=model_id, since=since, until=until)
        bucket_start = func.date_trunc(
            literal(bucket.value),
            UsageRow.created_at,
            literal("UTC"),
        ).label("bucket_start")
        total_tokens = func.sum(UsageRow.total_tokens)
        statement = (
            select(
                bucket_start,
                func.coalesce(func.sum(UsageRow.prompt_tokens), 0),
                func.coalesce(func.sum(UsageRow.completion_tokens), 0),
                func.coalesce(func.sum(UsageRow.cached_tokens), 0),
                func.coalesce(total_tokens, 0),
                func.count(),
            )
            .where(*filters)
            .group_by(bucket_start)
            .order_by(bucket_start.asc())
        )
        async with self._session_factory() as session, session.begin():
            rows = (await session.execute(statement)).all()
        return [
            UsagePoint(
                bucket_start=row[0],
                prompt_tokens=int(row[1]),
                completion_tokens=int(row[2]),
                cached_tokens=int(row[3]),
                total_tokens=int(row[4]),
                requests=int(row[5]),
            )
            for row in rows
        ]


def _parse_provider(value: str) -> ProviderName:
    try:
        return ProviderName(value)
    except ValueError as exc:
        raise ValueError(f"stored usage record has unknown provider {value!r}") from exc


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_audit_session(row: AuditSessionRow) -> AuditSessionRecord:
    return AuditSessionRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        external_session_id=row.external_session_id,
        api_key_id=row.api_key_id,
        api_key_prefix=row.api_key_prefix,
        root_request_id=row.root_request_id,
        model_id=row.model_id,
        provider=row.provider,
        title_preview=row.title_preview,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        request_count=row.request_count,
        total_tokens=row.total_tokens,
    )


def _to_audit_request(row: AuditRequestRow) -> AuditRequestRecord:
    match_method = row.match_method
    if match_method not in ("explicit", "prefix", "new"):
        raise ValueError(f"stored audit request has unknown match_method {match_method!r}")
    return AuditRequestRecord(
        request_id=row.request_id,
        session_id=row.session_id,
        parent_request_id=row.parent_request_id,
        tenant_id=row.tenant_id,
        api_key_id=row.api_key_id,
        turn_index=row.turn_index,
        match_method=match_method,
        change_type=row.change_type,
        model_id=row.model_id,
        provider=row.provider,
        is_stream=row.is_stream,
        request_messages=row.request_messages,
        message_hashes=row.message_hashes,
        request_params=row.request_params,
        response_content=row.response_content,
        response_tool_calls=row.response_tool_calls,
        response_content_hash=row.response_content_hash,
        finish_reason=row.finish_reason,
        status=row.status,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        cached_tokens=row.cached_tokens,
        total_tokens=row.total_tokens,
        truncated=row.truncated,
        created_at=row.created_at,
    )


def _to_audit_summary(row: Any) -> AuditRequestSummary:
    values = row._mapping
    match_method = values[AuditRequestRow.match_method]
    if match_method not in ("explicit", "prefix", "new"):
        raise ValueError(f"stored audit request has unknown match_method {match_method!r}")
    return AuditRequestSummary(
        request_id=values[AuditRequestRow.request_id],
        session_id=values[AuditRequestRow.session_id],
        parent_request_id=values[AuditRequestRow.parent_request_id],
        tenant_id=values[AuditRequestRow.tenant_id],
        api_key_id=values[AuditRequestRow.api_key_id],
        turn_index=values[AuditRequestRow.turn_index],
        match_method=match_method,
        change_type=values[AuditRequestRow.change_type],
        model_id=values[AuditRequestRow.model_id],
        provider=values[AuditRequestRow.provider],
        is_stream=values[AuditRequestRow.is_stream],
        finish_reason=values[AuditRequestRow.finish_reason],
        status=values[AuditRequestRow.status],
        prompt_tokens=values[AuditRequestRow.prompt_tokens],
        completion_tokens=values[AuditRequestRow.completion_tokens],
        cached_tokens=values[AuditRequestRow.cached_tokens],
        total_tokens=values[AuditRequestRow.total_tokens],
        truncated=values[AuditRequestRow.truncated],
        created_at=values[AuditRequestRow.created_at],
        request_message_count=values["request_message_count"],
    )


def _to_audit_diff(row: AuditTurnDiffRow) -> AuditTurnDiffRecord:
    return AuditTurnDiffRecord(
        request_id=row.request_id,
        previous_request_id=row.previous_request_id,
        change_type=row.change_type,
        common_prefix=row.common_prefix,
        added_messages=row.added_messages,
        modified_messages=row.modified_messages,
        removed_messages=row.removed_messages,
        parameter_changes=row.parameter_changes,
        usage_delta=row.usage_delta,
        response_change=row.response_change,
        created_at=row.created_at,
    )


def _audit_session_filters(
    filters: AuditSessionFilters,
) -> tuple[ColumnElement[bool], ...]:
    conditions: list[ColumnElement[bool]] = []
    if filters.tenant_id is not None:
        conditions.append(AuditSessionRow.tenant_id == filters.tenant_id)
    if filters.api_key_id is not None:
        conditions.append(AuditSessionRow.api_key_id == filters.api_key_id)
    if filters.model_id is not None:
        conditions.append(AuditSessionRow.model_id == filters.model_id)
    if filters.since is not None:
        conditions.append(AuditSessionRow.last_seen_at >= filters.since)
    if filters.until is not None:
        conditions.append(AuditSessionRow.last_seen_at < filters.until)
    if filters.q is not None:
        escaped = _escape_like(filters.q)
        request_id_matches = (
            select(AuditRequestRow.request_id)
            .where(
                AuditRequestRow.session_id == AuditSessionRow.id,
                AuditRequestRow.request_id.like(f"{escaped}%", escape="\\"),
            )
            .exists()
        )
        conditions.append(
            or_(
                sa_cast(AuditSessionRow.id, String).like(f"{escaped}%", escape="\\"),
                AuditSessionRow.root_request_id.like(f"{escaped}%", escape="\\"),
                request_id_matches,
                AuditSessionRow.title_preview.ilike(f"%{escaped}%", escape="\\"),
            )
        )
    return tuple(conditions)


def _audit_session_values(session: AuditSessionRecord) -> dict[str, object]:
    return {
        "id": session.id,
        "tenant_id": session.tenant_id,
        "external_session_id": session.external_session_id,
        "api_key_id": session.api_key_id,
        "api_key_prefix": session.api_key_prefix,
        "root_request_id": session.root_request_id,
        "model_id": session.model_id,
        "provider": session.provider,
        "title_preview": session.title_preview,
        "created_at": session.created_at,
        "last_seen_at": session.last_seen_at,
        "request_count": session.request_count,
        "total_tokens": session.total_tokens,
    }


def _to_audit_prefix(row: Any) -> AuditPrefixRecord:
    values = row._mapping
    return AuditPrefixRecord(
        request_id=values[AuditRequestRow.request_id],
        session_id=values[AuditRequestRow.session_id],
        turn_index=values[AuditRequestRow.turn_index],
        message_hashes=values[AuditRequestRow.message_hashes],
        created_at=values[AuditRequestRow.created_at],
    )


class SqlAlchemyAuditRepository:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_turn(
        self,
        *,
        session: AuditSessionRecord,
        request: AuditRequestRecord,
        diff: AuditTurnDiffRecord | None,
    ) -> None:
        async with self._session_factory() as db, db.begin():
            existing = await db.get(AuditSessionRow, session.id)
            if existing is None:
                db.add(
                    AuditSessionRow(
                        id=session.id,
                        tenant_id=session.tenant_id,
                        external_session_id=session.external_session_id,
                        api_key_id=session.api_key_id,
                        api_key_prefix=session.api_key_prefix,
                        root_request_id=session.root_request_id,
                        model_id=session.model_id,
                        provider=session.provider,
                        title_preview=session.title_preview,
                        created_at=session.created_at,
                        last_seen_at=session.last_seen_at,
                        request_count=session.request_count,
                        total_tokens=session.total_tokens,
                    )
                )
            else:
                values: dict[str, object] = {
                    "request_count": AuditSessionRow.request_count + 1,
                    "total_tokens": AuditSessionRow.total_tokens + (request.total_tokens or 0),
                    "last_seen_at": func.greatest(AuditSessionRow.last_seen_at, request.created_at),
                }
                # A session pre-created by ensure_session points at the first
                # attempted turn. Reconcile it with the turn that actually
                # persists so a failed attempt cannot leak its metadata.
                if existing.request_count == 0:
                    values.update(
                        {
                            "root_request_id": session.root_request_id,
                            "model_id": session.model_id,
                            "provider": session.provider,
                            "title_preview": session.title_preview,
                            "created_at": session.created_at,
                        }
                    )
                await db.execute(
                    update(AuditSessionRow).where(AuditSessionRow.id == session.id).values(**values)
                )
            # The unit of work has no relationship between these tables, so
            # flush the session row before the request that references it.
            await db.flush()
            db.add(
                AuditRequestRow(
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
                    request_messages=request.request_messages,
                    message_hashes=request.message_hashes,
                    request_params=request.request_params,
                    response_content=request.response_content,
                    response_tool_calls=request.response_tool_calls,
                    response_content_hash=request.response_content_hash,
                    finish_reason=request.finish_reason,
                    status=request.status,
                    prompt_tokens=request.prompt_tokens,
                    completion_tokens=request.completion_tokens,
                    cached_tokens=request.cached_tokens,
                    total_tokens=request.total_tokens,
                    truncated=request.truncated,
                    created_at=request.created_at,
                )
            )
            if diff is not None:
                db.add(
                    AuditTurnDiffRow(
                        request_id=diff.request_id,
                        previous_request_id=diff.previous_request_id,
                        change_type=diff.change_type,
                        common_prefix=diff.common_prefix,
                        added_messages=diff.added_messages,
                        modified_messages=diff.modified_messages,
                        removed_messages=diff.removed_messages,
                        parameter_changes=diff.parameter_changes,
                        usage_delta=diff.usage_delta,
                        response_change=diff.response_change,
                        created_at=diff.created_at,
                    )
                )

    async def get_session_by_external_id(
        self, *, tenant_id: UUID, external_session_id: str
    ) -> AuditSessionRecord | None:
        async with self._session_factory() as db, db.begin():
            row = await db.scalar(
                select(AuditSessionRow).where(
                    AuditSessionRow.tenant_id == tenant_id,
                    AuditSessionRow.external_session_id == external_session_id,
                )
            )
            return _to_audit_session(row) if row is not None else None

    async def ensure_session(self, *, session: AuditSessionRecord) -> AuditSessionRecord:
        async with self._session_factory() as db, db.begin():
            existing = await db.get(AuditSessionRow, session.id)
            if existing is not None:
                return _to_audit_session(existing)

            values = _audit_session_values(session)
            if session.external_session_id is not None:
                statement = (
                    pg_insert(AuditSessionRow)
                    .values(**values)
                    .on_conflict_do_nothing(
                        index_elements=[
                            AuditSessionRow.tenant_id,
                            AuditSessionRow.external_session_id,
                        ],
                        index_where=text("external_session_id IS NOT NULL"),
                    )
                )
                await db.execute(statement)
                row = await db.scalar(
                    select(AuditSessionRow).where(
                        AuditSessionRow.tenant_id == session.tenant_id,
                        AuditSessionRow.external_session_id == session.external_session_id,
                    )
                )
            else:
                statement = (
                    pg_insert(AuditSessionRow)
                    .values(**values)
                    .on_conflict_do_nothing(
                        index_elements=[AuditSessionRow.id],
                    )
                )
                await db.execute(statement)
                row = await db.get(AuditSessionRow, session.id)

            if row is None:
                raise RuntimeError("audit session insert did not persist")
            return _to_audit_session(row)

    async def get_latest_request(self, *, session_id: UUID) -> AuditRequestRecord | None:
        async with self._session_factory() as db, db.begin():
            row = await db.scalar(
                select(AuditRequestRow)
                .where(AuditRequestRow.session_id == session_id)
                .order_by(
                    AuditRequestRow.turn_index.desc(),
                    AuditRequestRow.created_at.desc(),
                    AuditRequestRow.request_id.desc(),
                )
                .limit(1)
            )
            return _to_audit_request(row) if row is not None else None

    async def recent_prefix_requests(
        self, *, tenant_id: UUID, api_key_id: UUID, since: datetime, limit: int
    ) -> list[AuditPrefixRecord]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        async with self._session_factory() as db, db.begin():
            rows = (
                await db.execute(
                    select(
                        AuditRequestRow.request_id,
                        AuditRequestRow.session_id,
                        AuditRequestRow.turn_index,
                        AuditRequestRow.message_hashes,
                        AuditRequestRow.created_at,
                    )
                    .where(
                        AuditRequestRow.tenant_id == tenant_id,
                        AuditRequestRow.api_key_id == api_key_id,
                        AuditRequestRow.created_at >= since,
                    )
                    .order_by(
                        AuditRequestRow.created_at.desc(),
                        AuditRequestRow.request_id.desc(),
                    )
                    .limit(limit)
                )
            ).all()
            return [_to_audit_prefix(row) for row in rows]

    async def list_sessions(
        self, *, filters: AuditSessionFilters, limit: int, offset: int
    ) -> AuditSessionPage:
        _validate_page(limit=limit, offset=offset)
        conditions = (*_audit_session_filters(filters), AuditSessionRow.request_count > 0)
        async with self._session_factory() as db, db.begin():
            rows = (
                await db.scalars(
                    select(AuditSessionRow)
                    .where(*conditions)
                    .order_by(
                        AuditSessionRow.last_seen_at.desc(),
                        AuditSessionRow.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            total = await db.scalar(
                select(func.count()).select_from(AuditSessionRow).where(*conditions)
            )
            return AuditSessionPage(
                items=[_to_audit_session(row) for row in rows],
                total=total or 0,
            )

    async def get_session(self, *, session_id: UUID) -> AuditSessionRecord | None:
        async with self._session_factory() as db, db.begin():
            row = await db.get(AuditSessionRow, session_id)
            return _to_audit_session(row) if row is not None else None

    async def list_session_requests(self, *, session_id: UUID) -> list[AuditRequestRecord]:
        async with self._session_factory() as db, db.begin():
            rows = (
                await db.scalars(
                    select(AuditRequestRow)
                    .where(AuditRequestRow.session_id == session_id)
                    .order_by(
                        AuditRequestRow.turn_index.asc(),
                        AuditRequestRow.created_at.asc(),
                        AuditRequestRow.request_id.asc(),
                    )
                )
            ).all()
            return [_to_audit_request(row) for row in rows]

    async def list_session_request_summaries(
        self, *, session_id: UUID
    ) -> list[AuditRequestSummary]:
        message_count = func.jsonb_array_length(AuditRequestRow.request_messages).label(
            "request_message_count"
        )
        async with self._session_factory() as db, db.begin():
            rows = (
                await db.execute(
                    select(
                        AuditRequestRow.request_id,
                        AuditRequestRow.session_id,
                        AuditRequestRow.parent_request_id,
                        AuditRequestRow.tenant_id,
                        AuditRequestRow.api_key_id,
                        AuditRequestRow.turn_index,
                        AuditRequestRow.match_method,
                        AuditRequestRow.change_type,
                        AuditRequestRow.model_id,
                        AuditRequestRow.provider,
                        AuditRequestRow.is_stream,
                        AuditRequestRow.finish_reason,
                        AuditRequestRow.status,
                        AuditRequestRow.prompt_tokens,
                        AuditRequestRow.completion_tokens,
                        AuditRequestRow.cached_tokens,
                        AuditRequestRow.total_tokens,
                        AuditRequestRow.truncated,
                        AuditRequestRow.created_at,
                        message_count,
                    )
                    .where(AuditRequestRow.session_id == session_id)
                    .order_by(
                        AuditRequestRow.turn_index.asc(),
                        AuditRequestRow.created_at.asc(),
                        AuditRequestRow.request_id.asc(),
                    )
                )
            ).all()
            return [_to_audit_summary(row) for row in rows]

    async def get_diffs(self, *, request_ids: Sequence[str]) -> dict[str, AuditTurnDiffRecord]:
        if not request_ids:
            return {}
        async with self._session_factory() as db, db.begin():
            rows = (
                await db.scalars(
                    select(AuditTurnDiffRow).where(AuditTurnDiffRow.request_id.in_(request_ids))
                )
            ).all()
            return {row.request_id: _to_audit_diff(row) for row in rows}

    async def get_request(self, *, request_id: str) -> AuditRequestRecord | None:
        async with self._session_factory() as db, db.begin():
            row = await db.get(AuditRequestRow, request_id)
            return _to_audit_request(row) if row is not None else None

    async def get_diff(self, *, request_id: str) -> AuditTurnDiffRecord | None:
        async with self._session_factory() as db, db.begin():
            row = await db.get(AuditTurnDiffRow, request_id)
            return _to_audit_diff(row) if row is not None else None
