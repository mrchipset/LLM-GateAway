from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from llm_gateway.config import Environment, Settings, StorageBackend
from llm_gateway.providers.base import ProviderName
from llm_gateway.storage.db import Database
from llm_gateway.storage.repositories import (
    DEFAULT_TENANT_ID,
    ApiKeyRecord,
    DuplicateApiKeyError,
    DuplicateModelError,
    DuplicateTenantError,
    ModelConfig,
    Tenant,
    TenantLimitPatch,
    UnknownTenantError,
    UsageRecord,
)

_TEST_DATABASE_URL = os.environ.get("GATEWAY_TEST_DATABASE_URL")
_REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _TEST_DATABASE_URL,
        reason="GATEWAY_TEST_DATABASE_URL is not set",
    ),
]

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _test_url() -> str:
    if not _TEST_DATABASE_URL:
        raise RuntimeError("GATEWAY_TEST_DATABASE_URL is not set")
    return _TEST_DATABASE_URL


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _model(index: int, *, enabled: bool = True) -> ModelConfig:
    return ModelConfig(
        id=f"model-{index}",
        provider=ProviderName.FAKE,
        upstream_model=f"upstream-{index}",
        created_at=BASE + timedelta(seconds=index),
        enabled=enabled,
    )


def _tenant(index: int, *, name: str | None = None) -> Tenant:
    return Tenant(
        id=uuid4(),
        name=name if name is not None else f"tenant-{index}",
        created_at=BASE + timedelta(seconds=index),
    )


def _key(index: int, *, tenant_id: UUID, key_hash: str | None = None) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        name=f"key-{index}",
        key_hash=key_hash if key_hash is not None else _hash(f"key-{index}"),
        key_prefix=f"sk-gw-{index:06d}",
        created_at=BASE + timedelta(seconds=index),
    )


def _usage(
    index: int,
    *,
    tenant_id: UUID,
    api_key_id: UUID,
    model_id: str = "model-1",
    provider: ProviderName = ProviderName.FAKE,
    created_at: datetime | None = None,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    cached_tokens: int = 0,
) -> UsageRecord:
    return UsageRecord(
        id=uuid4(),
        request_id=f"req-{index}",
        tenant_id=tenant_id,
        api_key_id=api_key_id,
        model_id=model_id,
        provider=provider,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cached_tokens=cached_tokens,
        created_at=created_at if created_at is not None else BASE + timedelta(seconds=index),
    )


def _build_settings() -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": "test-master-key-0123456789abcdef",
            "storage_backend": StorageBackend.POSTGRES,
            "database_url": _test_url(),
        }
    )


async def _truncate() -> None:
    engine = create_async_engine(_test_url())
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE api_keys, models, tenants, usage_records, tenant_rate_limits "
                    "RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def migrated_schema() -> Iterator[None]:
    # alembic/env.py reads GATEWAY_DATABASE_URL directly so migrations never
    # depend on the application Settings (which would require a master key).
    previous = os.environ.get("GATEWAY_DATABASE_URL")
    os.environ["GATEWAY_DATABASE_URL"] = _test_url()
    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
        command.upgrade(config, "head")
        yield
    finally:
        if previous is None:
            os.environ.pop("GATEWAY_DATABASE_URL", None)
        else:
            os.environ["GATEWAY_DATABASE_URL"] = previous


@pytest.fixture
def postgres_settings(migrated_schema: None) -> Settings:
    return _build_settings()


@pytest.fixture
async def database(postgres_settings: Settings) -> AsyncIterator[Database]:
    await _truncate()
    db = Database.from_settings(postgres_settings)
    try:
        yield db
    finally:
        await db.aclose()


async def test_model_round_trip_preserves_fields(database: Database) -> None:
    model = _model(1)

    created = await database.models.create_model(model)
    stored = await database.models.get_model(model.id)

    assert created == model, "create_model must return the persisted domain record"
    assert stored == model, "stored model must round-trip unchanged"
    assert stored is not None
    assert stored.provider is ProviderName.FAKE
    assert stored.created_at.tzinfo is not None, "created_at must stay timezone-aware"


async def test_model_list_is_newest_first_with_pagination(database: Database) -> None:
    for index in range(5):
        await database.models.create_model(_model(index))

    items, total = await database.models.list_models(limit=2, offset=1)

    assert total == 5
    assert [item.id for item in items] == ["model-3", "model-2"]


async def test_model_list_enabled_only_filters_before_pagination(database: Database) -> None:
    await database.models.create_model(_model(0))
    await database.models.create_model(_model(1))
    await database.models.create_model(_model(2, enabled=False))

    items, total = await database.models.list_models(limit=1, offset=0, enabled_only=True)

    assert total == 2, "total must count only enabled models"
    assert [item.id for item in items] == ["model-1"]


async def test_model_duplicate_create_raises(database: Database) -> None:
    model = _model(1)
    await database.models.create_model(model)

    with pytest.raises(DuplicateModelError, match="model 'model-1' already exists"):
        await database.models.create_model(model)


async def test_model_delete_returns_false_once_missing(database: Database) -> None:
    model = _model(1)
    await database.models.create_model(model)

    assert await database.models.delete_model(model.id) is True
    assert await database.models.get_model(model.id) is None
    assert await database.models.delete_model(model.id) is False


@pytest.mark.parametrize(
    ("limit", "offset", "message"),
    [(0, 0, "limit must be >= 1"), (-1, 0, "limit must be >= 1"), (1, -1, "offset must be >= 0")],
)
async def test_model_list_rejects_invalid_pagination(
    database: Database, limit: int, offset: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        await database.models.list_models(limit=limit, offset=offset)


async def test_tenant_round_trip_and_list(database: Database) -> None:
    tenant = _tenant(1)

    created = await database.tenants.create_tenant(tenant)

    assert created == tenant
    assert await database.tenants.get_tenant(tenant.id) == tenant
    assert await database.tenants.get_tenant(uuid4()) is None
    items, total = await database.tenants.list_tenants(limit=10, offset=0)
    assert [item.id for item in items] == [tenant.id]
    assert total == 1


async def test_tenant_duplicate_name_raises(database: Database) -> None:
    await database.tenants.create_tenant(_tenant(1))

    with pytest.raises(DuplicateTenantError, match="tenant 'tenant-1' already exists"):
        await database.tenants.create_tenant(_tenant(2, name="tenant-1"))


async def test_tenant_list_is_newest_first_with_pagination(database: Database) -> None:
    for index in range(5):
        await database.tenants.create_tenant(_tenant(index))

    items, total = await database.tenants.list_tenants(limit=2, offset=1)

    assert total == 5
    assert [item.name for item in items] == ["tenant-3", "tenant-2"]


async def test_tenant_list_rejects_invalid_pagination(database: Database) -> None:
    with pytest.raises(ValueError, match="offset must be >= 0"):
        await database.tenants.list_tenants(limit=1, offset=-1)


async def test_api_key_round_trip_preserves_fields(database: Database) -> None:
    tenant = await database.tenants.create_tenant(_tenant(1))
    key = _key(1, tenant_id=tenant.id)

    created = await database.api_keys.create_key(key)

    assert created == key, "create_key must return the persisted domain record"
    assert await database.api_keys.get_key(key.id) == key
    assert await database.api_keys.get_key_by_hash(key.key_hash) == key
    assert await database.api_keys.get_key(uuid4()) is None
    assert await database.api_keys.get_key_by_hash(_hash("missing")) is None


async def test_api_key_duplicate_hash_raises(database: Database) -> None:
    tenant = await database.tenants.create_tenant(_tenant(1))
    shared_hash = _hash("shared")
    await database.api_keys.create_key(_key(1, tenant_id=tenant.id, key_hash=shared_hash))

    with pytest.raises(DuplicateApiKeyError):
        await database.api_keys.create_key(_key(2, tenant_id=tenant.id, key_hash=shared_hash))


async def test_api_key_revoke_transitions_once(database: Database) -> None:
    tenant = await database.tenants.create_tenant(_tenant(1))
    key = _key(1, tenant_id=tenant.id)
    await database.api_keys.create_key(key)

    assert await database.api_keys.revoke_key(key.id, BASE) is True
    revoked = await database.api_keys.get_key(key.id)
    assert revoked is not None
    assert revoked.revoked_at == BASE
    assert await database.api_keys.revoke_key(key.id, BASE) is False


async def test_api_key_touch_last_used_updates_record(database: Database) -> None:
    tenant = await database.tenants.create_tenant(_tenant(1))
    key = _key(1, tenant_id=tenant.id)
    await database.api_keys.create_key(key)

    await database.api_keys.touch_last_used(key.id, BASE)

    updated = await database.api_keys.get_key(key.id)
    assert updated is not None
    assert updated.last_used_at == BASE


async def test_api_key_touch_last_used_raises_for_missing_key(database: Database) -> None:
    with pytest.raises(KeyError, match="not found"):
        await database.api_keys.touch_last_used(uuid4(), BASE)


async def test_api_key_fk_rejects_unknown_tenant(database: Database) -> None:
    with pytest.raises(UnknownTenantError):
        await database.api_keys.create_key(_key(1, tenant_id=uuid4()))


async def test_api_key_list_is_newest_first_with_pagination(database: Database) -> None:
    tenant = await database.tenants.create_tenant(_tenant(1))
    for index in range(5):
        await database.api_keys.create_key(_key(index, tenant_id=tenant.id))

    items, total = await database.api_keys.list_keys(limit=2, offset=1)

    assert total == 5
    assert [item.name for item in items] == ["key-3", "key-2"]


async def test_api_key_list_filters_by_tenant_before_pagination(database: Database) -> None:
    tenant_a = await database.tenants.create_tenant(_tenant(1))
    tenant_b = await database.tenants.create_tenant(_tenant(2))
    await database.api_keys.create_key(_key(0, tenant_id=tenant_a.id))
    await database.api_keys.create_key(_key(1, tenant_id=tenant_a.id))
    await database.api_keys.create_key(_key(2, tenant_id=tenant_b.id))

    items, total = await database.api_keys.list_keys(limit=10, offset=0, tenant_id=tenant_b.id)

    assert total == 1
    assert [item.name for item in items] == ["key-2"]

    page, filtered_total = await database.api_keys.list_keys(
        limit=1, offset=1, tenant_id=tenant_a.id
    )

    assert filtered_total == 2
    assert [item.name for item in page] == ["key-0"]


async def test_api_key_list_rejects_invalid_pagination(database: Database) -> None:
    with pytest.raises(ValueError, match="limit must be >= 1"):
        await database.api_keys.list_keys(limit=0, offset=0)


async def test_tenant_set_limits_round_trip_and_clear(database: Database) -> None:
    tenant = await database.tenants.create_tenant(_tenant(1))

    updated = await database.tenants.set_tenant_limits(
        tenant.id,
        patch=TenantLimitPatch(
            monthly_token_quota=1000,
            requests_per_minute=5,
            set_monthly_token_quota=True,
            set_requests_per_minute=True,
        ),
    )

    assert updated is not None
    assert updated.monthly_token_quota == 1000
    assert updated.requests_per_minute == 5
    assert await database.tenants.get_tenant(tenant.id) == updated

    cleared = await database.tenants.set_tenant_limits(
        tenant.id,
        patch=TenantLimitPatch(
            set_monthly_token_quota=True,
            set_requests_per_minute=True,
        ),
    )
    assert cleared is not None
    assert cleared.monthly_token_quota is None
    assert cleared.requests_per_minute is None

    missing = await database.tenants.set_tenant_limits(
        uuid4(),
        patch=TenantLimitPatch(
            monthly_token_quota=1,
            requests_per_minute=1,
            set_monthly_token_quota=True,
            set_requests_per_minute=True,
        ),
    )
    assert missing is None


async def test_usage_token_total_filters_and_is_half_open(database: Database) -> None:
    tenant_a = await database.tenants.create_tenant(_tenant(1))
    tenant_b = await database.tenants.create_tenant(_tenant(2))
    key_a = _key(1, tenant_id=tenant_a.id)
    key_b = _key(2, tenant_id=tenant_b.id)
    await database.api_keys.create_key(key_a)
    await database.api_keys.create_key(key_b)
    await database.usage.record(
        _usage(
            1,
            tenant_id=tenant_a.id,
            api_key_id=key_a.id,
            created_at=BASE,
            prompt_tokens=10,
            completion_tokens=0,
        )
    )
    await database.usage.record(
        _usage(
            2,
            tenant_id=tenant_a.id,
            api_key_id=key_a.id,
            created_at=BASE + timedelta(minutes=1),
            prompt_tokens=20,
            completion_tokens=0,
        )
    )
    await database.usage.record(
        _usage(
            3,
            tenant_id=tenant_b.id,
            api_key_id=key_b.id,
            created_at=BASE,
            prompt_tokens=100,
            completion_tokens=0,
        )
    )

    assert (
        await database.usage.token_total(
            tenant_id=tenant_a.id,
            since=BASE,
            until=BASE + timedelta(minutes=2),
        )
        == 30
    )
    assert (
        await database.usage.token_total(
            tenant_id=tenant_a.id,
            since=BASE,
            until=BASE + timedelta(minutes=1),
        )
        == 10
    )
    assert (
        await database.usage.token_total(
            tenant_id=tenant_a.id,
            since=BASE + timedelta(minutes=1),
            until=BASE + timedelta(minutes=2),
        )
        == 20
    )

    with pytest.raises(ValueError, match="since must be before until"):
        await database.usage.token_total(
            tenant_id=tenant_a.id,
            since=BASE,
            until=BASE,
        )


async def test_rate_limiter_is_atomic_across_concurrent_hits(database: Database) -> None:
    tenant = await database.tenants.create_tenant(_tenant(1))

    results = await asyncio.gather(
        *(database.rate_limiter.hit(tenant_id=tenant.id, limit=10, now=BASE) for _ in range(20))
    )

    assert sum(result.allowed for result in results) == 10
    engine = create_async_engine(_test_url())
    try:
        async with engine.connect() as connection:
            count = await connection.scalar(
                text("SELECT count FROM tenant_rate_limits WHERE tenant_id = :id"),
                {"id": tenant.id},
            )
        assert count == 20

        rolled = await database.rate_limiter.hit(
            tenant_id=tenant.id,
            limit=10,
            now=BASE + timedelta(seconds=61),
        )
        assert rolled.allowed is True
        async with engine.connect() as connection:
            rolled_count = await connection.scalar(
                text("SELECT count FROM tenant_rate_limits WHERE tenant_id = :id"),
                {"id": tenant.id},
            )
        assert rolled_count == 1
    finally:
        await engine.dispose()


async def test_rate_limiter_rejects_unknown_tenant(database: Database) -> None:
    with pytest.raises(UnknownTenantError):
        await database.rate_limiter.hit(tenant_id=uuid4(), limit=1, now=BASE)


async def test_rate_limiter_ignores_stale_clock_window(database: Database) -> None:
    tenant = await database.tenants.create_tenant(_tenant(1))

    first = await database.rate_limiter.hit(tenant_id=tenant.id, limit=1, now=BASE)
    newer = await database.rate_limiter.hit(
        tenant_id=tenant.id, limit=1, now=BASE + timedelta(seconds=61)
    )
    stale = await database.rate_limiter.hit(
        tenant_id=tenant.id, limit=1, now=BASE + timedelta(seconds=30)
    )
    still_stored = await database.rate_limiter.hit(
        tenant_id=tenant.id, limit=1, now=BASE + timedelta(seconds=62)
    )

    assert first.allowed is True
    assert newer.allowed is True
    assert stale.allowed is False
    assert still_stored.allowed is False
    assert 0 <= stale.retry_after_seconds <= 60

    engine = create_async_engine(_test_url())
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT count, window_start FROM tenant_rate_limits WHERE tenant_id = :id"
                    ),
                    {"id": tenant.id},
                )
            ).one()
        assert row[0] == 3
        assert row[1] == BASE + timedelta(minutes=1)
    finally:
        await engine.dispose()


async def test_ping_returns_true_and_aclose_allows_new_database(
    postgres_settings: Settings,
) -> None:
    first = Database.from_settings(postgres_settings)
    assert await first.ping() is True
    await first.aclose()

    second = Database.from_settings(postgres_settings)
    try:
        assert await second.ping() is True
    finally:
        await second.aclose()


def _run_migration(direction: str, revision: str) -> None:
    previous = os.environ.get("GATEWAY_DATABASE_URL")
    os.environ["GATEWAY_DATABASE_URL"] = _test_url()
    try:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
        if direction == "downgrade":
            command.downgrade(config, revision)
        else:
            command.upgrade(config, revision)
    finally:
        if previous is None:
            os.environ.pop("GATEWAY_DATABASE_URL", None)
        else:
            os.environ["GATEWAY_DATABASE_URL"] = previous


async def test_migration_creates_default_tenant_and_not_null_column(
    migrated_schema: None,
) -> None:
    await asyncio.to_thread(_run_migration, "downgrade", "0001")
    engine = create_async_engine(_test_url())
    try:
        await asyncio.to_thread(_run_migration, "upgrade", "head")
        async with engine.connect() as connection:
            tenant_name = await connection.scalar(
                text("SELECT name FROM tenants WHERE id = :id"),
                {"id": DEFAULT_TENANT_ID},
            )
            nullable = await connection.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'api_keys' AND column_name = 'tenant_id'"
                )
            )
        assert tenant_name == "default"
        assert nullable == "NO"
    finally:
        await asyncio.to_thread(_run_migration, "upgrade", "head")
        await engine.dispose()


async def test_migration_creates_usage_records_table(migrated_schema: None) -> None:
    engine = create_async_engine(_test_url())
    try:
        async with engine.connect() as connection:
            table_name = await connection.scalar(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_name = 'usage_records'"
                )
            )
            nullable = await connection.scalar(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'usage_records' AND column_name = 'tenant_id'"
                )
            )
        assert table_name == "usage_records"
        assert nullable == "NO"
    finally:
        await engine.dispose()


async def test_migration_adds_tenant_limits_and_rate_limit_table(
    migrated_schema: None,
) -> None:
    engine = create_async_engine(_test_url())
    try:
        async with engine.connect() as connection:
            limit_columns = (
                await connection.scalars(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'tenants' "
                        "AND column_name IN ('monthly_token_quota', 'requests_per_minute')"
                    )
                )
            ).all()
            rate_table = await connection.scalar(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_name = 'tenant_rate_limits'"
                )
            )
        assert set(limit_columns) == {"monthly_token_quota", "requests_per_minute"}
        assert rate_table == "tenant_rate_limits"
    finally:
        await engine.dispose()


async def test_migration_backfills_existing_keys_with_default_tenant(
    migrated_schema: None,
) -> None:
    await asyncio.to_thread(_run_migration, "downgrade", "0001")
    key_id = uuid4()
    engine = create_async_engine(_test_url())
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO api_keys "
                    "(id, name, key_hash, key_prefix, created_at) "
                    "VALUES (:id, :name, :key_hash, :key_prefix, now())"
                ),
                {
                    "id": key_id,
                    "name": "legacy-key",
                    "key_hash": _hash("legacy-key"),
                    "key_prefix": "sk-gw-legacy",
                },
            )

        await asyncio.to_thread(_run_migration, "upgrade", "head")

        async with engine.connect() as connection:
            tenant_id = await connection.scalar(
                text("SELECT tenant_id FROM api_keys WHERE id = :id"),
                {"id": key_id},
            )
        assert tenant_id == DEFAULT_TENANT_ID
    finally:
        await asyncio.to_thread(_run_migration, "upgrade", "head")
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM api_keys WHERE id = :id"), {"id": key_id})
        await engine.dispose()


async def test_usage_record_round_trip_and_summary(database: Database) -> None:
    tenant = await database.tenants.create_tenant(_tenant(1))
    key = _key(1, tenant_id=tenant.id)
    await database.api_keys.create_key(key)
    record = _usage(1, tenant_id=tenant.id, api_key_id=key.id)

    await database.usage.record(record)

    by_model = await database.usage.summary_by_model(
        tenant_id=None, model_id=None, since=None, until=None
    )
    assert len(by_model) == 1
    assert by_model[0].model_id == "model-1"
    assert by_model[0].provider is ProviderName.FAKE
    assert by_model[0].prompt_tokens == 10
    assert by_model[0].completion_tokens == 5
    assert by_model[0].cached_tokens == 0
    assert by_model[0].total_tokens == 15
    assert by_model[0].requests == 1


async def test_usage_summary_filters_and_by_model_ordering(database: Database) -> None:
    tenant_a = await database.tenants.create_tenant(_tenant(1))
    tenant_b = await database.tenants.create_tenant(_tenant(2))
    key_a = _key(1, tenant_id=tenant_a.id)
    key_b = _key(2, tenant_id=tenant_b.id)
    await database.api_keys.create_key(key_a)
    await database.api_keys.create_key(key_b)
    await database.usage.record(
        _usage(
            1,
            tenant_id=tenant_a.id,
            api_key_id=key_a.id,
            model_id="model-a",
            created_at=BASE + timedelta(hours=1),
            prompt_tokens=10,
            completion_tokens=5,
            cached_tokens=2,
        )
    )
    await database.usage.record(
        _usage(
            2,
            tenant_id=tenant_a.id,
            api_key_id=key_a.id,
            model_id="model-b",
            created_at=BASE + timedelta(hours=2),
            prompt_tokens=20,
            completion_tokens=10,
        )
    )
    await database.usage.record(
        _usage(
            3,
            tenant_id=tenant_b.id,
            api_key_id=key_b.id,
            model_id="model-a",
            created_at=BASE + timedelta(hours=3),
            prompt_tokens=7,
            completion_tokens=3,
            cached_tokens=1,
        )
    )

    tenant_models = await database.usage.summary_by_model(
        tenant_id=tenant_a.id, model_id=None, since=None, until=None
    )
    assert sum(item.total_tokens for item in tenant_models) == 45
    assert sum(item.requests for item in tenant_models) == 2

    by_model = await database.usage.summary_by_model(
        tenant_id=None, model_id=None, since=None, until=None
    )
    assert [item.model_id for item in by_model] == ["model-b", "model-a"]
    assert [item.total_tokens for item in by_model] == [30, 25]

    since_models = await database.usage.summary_by_model(
        tenant_id=None,
        model_id=None,
        since=BASE + timedelta(hours=2),
        until=None,
    )
    assert sum(item.requests for item in since_models) == 2
    assert sum(item.total_tokens for item in since_models) == 40

    until_models = await database.usage.summary_by_model(
        tenant_id=None,
        model_id=None,
        since=None,
        until=BASE + timedelta(hours=2),
    )
    assert sum(item.requests for item in until_models) == 1
    assert sum(item.total_tokens for item in until_models) == 15


async def test_usage_record_rejects_unknown_tenant(database: Database) -> None:
    tenant = await database.tenants.create_tenant(_tenant(1))
    key = _key(1, tenant_id=tenant.id)
    await database.api_keys.create_key(key)

    with pytest.raises(UnknownTenantError):
        await database.usage.record(_usage(1, tenant_id=uuid4(), api_key_id=key.id))


async def test_usage_record_rejects_unknown_api_key(database: Database) -> None:
    tenant = await database.tenants.create_tenant(_tenant(1))

    with pytest.raises(IntegrityError):
        await database.usage.record(_usage(1, tenant_id=tenant.id, api_key_id=uuid4()))
