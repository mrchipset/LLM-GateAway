from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from llm_gateway.providers.base import ProviderName
from llm_gateway.storage.repositories import (
    ApiKeyRecord,
    DuplicateApiKeyError,
    DuplicateModelError,
    ModelConfig,
)
from llm_gateway.storage.tables import ApiKeyRow, ModelRow

_UNIQUE_VIOLATION_SQLSTATE = "23505"


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


def _to_key(row: ApiKeyRow) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=row.id,
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


class SqlAlchemyApiKeyRepository:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_key(self, record: ApiKeyRecord) -> ApiKeyRecord:
        row = ApiKeyRow(
            id=record.id,
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
            raise DuplicateApiKeyError() from exc
        return record

    async def get_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(select(ApiKeyRow).where(ApiKeyRow.key_hash == key_hash))
            return _to_key(row) if row is not None else None

    async def get_key(self, key_id: UUID) -> ApiKeyRecord | None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(ApiKeyRow, key_id)
            return _to_key(row) if row is not None else None

    async def list_keys(self, *, limit: int, offset: int) -> tuple[Sequence[ApiKeyRecord], int]:
        _validate_page(limit=limit, offset=offset)
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.scalars(
                    select(ApiKeyRow)
                    .order_by(ApiKeyRow.created_at.desc(), ApiKeyRow.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            total = await session.scalar(select(func.count()).select_from(ApiKeyRow))
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
