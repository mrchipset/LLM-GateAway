from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, literal, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from llm_gateway.providers.base import ProviderName
from llm_gateway.storage.repositories import (
    ApiKeyRecord,
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
from llm_gateway.storage.tables import ApiKeyRow, ModelRow, TenantRow, UsageRow

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
        values: dict[str, int | None] = {}
        if patch.set_monthly_token_quota:
            values["monthly_token_quota"] = patch.monthly_token_quota
        if patch.set_requests_per_minute:
            values["requests_per_minute"] = patch.requests_per_minute
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
