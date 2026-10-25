from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from llm_gateway.auth.keys import hash_api_key
from llm_gateway.providers.base import ProviderName
from llm_gateway.storage.memory import InMemoryApiKeyRepository, InMemoryUsageRepository
from llm_gateway.storage.repositories import (
    ApiKeyRecord,
    TimeBucket,
    UsageRecord,
)

BASE = datetime(2026, 1, 2, 10, 0, tzinfo=UTC)
TENANT_A = uuid4()
TENANT_B = uuid4()
KEY_1 = UUID(int=1)
KEY_2 = UUID(int=2)
KEY_3 = UUID(int=3)


def _record(
    *,
    api_key_id: UUID,
    tenant_id: UUID = TENANT_A,
    model_id: str = "model-a",
    created_at: datetime,
    prompt_tokens: int = 1,
    completion_tokens: int = 0,
    cached_tokens: int = 0,
    total_tokens: int | None = None,
) -> UsageRecord:
    return UsageRecord(
        id=uuid4(),
        request_id=f"req-{uuid4()}",
        tenant_id=tenant_id,
        api_key_id=api_key_id,
        model_id=model_id,
        provider=ProviderName.FAKE,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        total_tokens=(
            total_tokens if total_tokens is not None else prompt_tokens + completion_tokens
        ),
        created_at=created_at,
    )


async def _seed_by_key(repository: InMemoryUsageRepository) -> None:
    await repository.record(
        _record(
            api_key_id=KEY_1,
            created_at=BASE + timedelta(hours=1),
            prompt_tokens=10,
            completion_tokens=5,
            cached_tokens=2,
            total_tokens=15,
        )
    )
    await repository.record(
        _record(
            api_key_id=KEY_1,
            created_at=BASE + timedelta(hours=2),
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
        )
    )
    await repository.record(
        _record(
            api_key_id=KEY_2,
            model_id="model-b",
            created_at=BASE + timedelta(hours=3),
            prompt_tokens=5,
            completion_tokens=1,
            cached_tokens=1,
            total_tokens=6,
        )
    )
    await repository.record(
        _record(
            api_key_id=KEY_3,
            tenant_id=TENANT_B,
            created_at=BASE + timedelta(hours=4),
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        )
    )


async def test_summary_by_key_aggregates_orders_and_filters() -> None:
    repository = InMemoryUsageRepository()
    await _seed_by_key(repository)

    items = await repository.summary_by_key(
        tenant_id=None,
        model_id=None,
        since=None,
        until=None,
    )

    assert [item.api_key_id for item in items] == [KEY_1, KEY_2, KEY_3]
    assert items[0].prompt_tokens == 30
    assert items[0].completion_tokens == 15
    assert items[0].cached_tokens == 2
    assert items[0].total_tokens == 45
    assert items[0].requests == 2
    assert items[1].total_tokens == 6
    assert items[2].total_tokens == 2

    tenant_b = await repository.summary_by_key(
        tenant_id=TENANT_B,
        model_id=None,
        since=None,
        until=None,
    )
    assert [item.api_key_id for item in tenant_b] == [KEY_3]

    model_a = await repository.summary_by_key(
        tenant_id=TENANT_A,
        model_id="model-a",
        since=None,
        until=None,
    )
    assert [item.api_key_id for item in model_a] == [KEY_1]

    windowed = await repository.summary_by_key(
        tenant_id=None,
        model_id=None,
        since=BASE + timedelta(hours=2),
        until=BASE + timedelta(hours=4),
    )
    assert [item.api_key_id for item in windowed] == [KEY_1, KEY_2]
    assert [item.total_tokens for item in windowed] == [30, 6]

    empty = await repository.summary_by_key(
        tenant_id=None,
        model_id="missing-model",
        since=None,
        until=None,
    )
    assert list(empty) == []


async def test_summary_by_key_breaks_total_ties_by_key_id() -> None:
    repository = InMemoryUsageRepository()
    lower_id = UUID(int=10)
    higher_id = UUID(int=20)
    await repository.record(_record(api_key_id=higher_id, created_at=BASE, total_tokens=5))
    await repository.record(_record(api_key_id=lower_id, created_at=BASE, total_tokens=5))

    items = await repository.summary_by_key(
        tenant_id=None,
        model_id=None,
        since=None,
        until=None,
    )

    assert [item.api_key_id for item in items] == [lower_id, higher_id]


async def test_summary_series_hour_buckets_across_minute_boundary() -> None:
    repository = InMemoryUsageRepository()
    await repository.record(
        _record(api_key_id=KEY_1, created_at=datetime(2026, 1, 2, 10, 59, 30, tzinfo=UTC))
    )
    await repository.record(
        _record(api_key_id=KEY_1, created_at=datetime(2026, 1, 2, 10, 59, 59, tzinfo=UTC))
    )
    await repository.record(
        _record(api_key_id=KEY_2, created_at=datetime(2026, 1, 2, 11, 0, 30, tzinfo=UTC))
    )

    points = await repository.summary_series(
        tenant_id=None,
        model_id=None,
        since=None,
        until=None,
        bucket=TimeBucket.HOUR,
    )

    assert [point.bucket_start for point in points] == [
        datetime(2026, 1, 2, 10, 0, tzinfo=UTC),
        datetime(2026, 1, 2, 11, 0, tzinfo=UTC),
    ]
    assert [point.total_tokens for point in points] == [2, 1]
    assert [point.requests for point in points] == [2, 1]


async def test_summary_series_day_buckets_straddle_utc_midnight() -> None:
    repository = InMemoryUsageRepository()
    await repository.record(
        _record(api_key_id=KEY_1, created_at=datetime(2026, 1, 2, 23, 30, tzinfo=UTC))
    )
    await repository.record(
        _record(api_key_id=KEY_1, created_at=datetime(2026, 1, 3, 0, 30, tzinfo=UTC))
    )

    points = await repository.summary_series(
        tenant_id=None,
        model_id=None,
        since=None,
        until=None,
        bucket=TimeBucket.DAY,
    )

    assert [point.bucket_start for point in points] == [
        datetime(2026, 1, 2, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 3, 0, 0, tzinfo=UTC),
    ]
    assert [point.total_tokens for point in points] == [1, 1]


async def test_summary_series_filters_and_half_open_boundaries() -> None:
    repository = InMemoryUsageRepository()
    await repository.record(
        _record(
            api_key_id=KEY_1,
            created_at=datetime(2026, 1, 2, 10, 30, tzinfo=UTC),
        )
    )
    await repository.record(
        _record(
            api_key_id=KEY_1,
            created_at=datetime(2026, 1, 2, 11, 30, tzinfo=UTC),
        )
    )
    await repository.record(
        _record(
            api_key_id=KEY_1,
            tenant_id=TENANT_B,
            created_at=datetime(2026, 1, 2, 12, 30, tzinfo=UTC),
        )
    )
    await repository.record(
        _record(
            api_key_id=KEY_1,
            model_id="model-b",
            created_at=datetime(2026, 1, 2, 13, 30, tzinfo=UTC),
        )
    )

    points = await repository.summary_series(
        tenant_id=TENANT_A,
        model_id="model-a",
        since=datetime(2026, 1, 2, 11, 0, tzinfo=UTC),
        until=datetime(2026, 1, 2, 13, 0, tzinfo=UTC),
        bucket=TimeBucket.HOUR,
    )

    assert [point.bucket_start for point in points] == [
        datetime(2026, 1, 2, 11, 0, tzinfo=UTC),
    ]
    assert points[0].requests == 1


async def test_get_keys_short_circuits_and_returns_only_requested() -> None:
    repository = InMemoryApiKeyRepository()
    first_id = uuid4()
    second_id = uuid4()
    third_id = uuid4()
    for key_id in (first_id, second_id, third_id):
        await repository.create_key(
            ApiKeyRecord(
                id=key_id,
                tenant_id=TENANT_A,
                name=f"key-{key_id}",
                key_hash=hash_api_key(str(key_id)),
                key_prefix="sk-gw-000001",
                created_at=BASE,
            )
        )

    assert list(await repository.get_keys([])) == []

    records = await repository.get_keys([first_id, third_id])

    assert {record.id for record in records} == {first_id, third_id}
