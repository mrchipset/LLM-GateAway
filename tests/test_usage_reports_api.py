from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx

from llm_gateway.auth.keys import hash_api_key
from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.storage.repositories import ApiKeyRecord, Tenant
from support import FrozenClock, seed_tenant, seed_usage

BASE = datetime(2026, 1, 1, 10, 15, tzinfo=UTC)


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _master(settings: Settings) -> str:
    return settings.master_key.get_secret_value()


def _error(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    error = body["error"]
    assert isinstance(error, dict)
    return error


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def _create_key(
    container: Container,
    *,
    tenant: Tenant,
    name: str,
    prefix: str,
) -> ApiKeyRecord:
    record = ApiKeyRecord(
        id=uuid4(),
        tenant_id=tenant.id,
        name=name,
        key_hash=hash_api_key(f"{name}-{uuid4()}"),
        key_prefix=prefix,
        created_at=container.clock.now(),
    )
    await container.api_keys.create_key(record)
    return record


async def _seed_by_key(
    container: Container,
) -> tuple[Tenant, Tenant, ApiKeyRecord, ApiKeyRecord, ApiKeyRecord, UUID]:
    tenant_a = await seed_tenant(container, name="tenant-a")
    tenant_b = await seed_tenant(container, name="tenant-b")
    key_a = await _create_key(container, tenant=tenant_a, name="key-a", prefix="sk-gw-aaa")
    key_b = await _create_key(container, tenant=tenant_a, name="key-b", prefix="sk-gw-bbb")
    tenant_b_key = await _create_key(container, tenant=tenant_b, name="key-c", prefix="sk-gw-ccc")
    missing_key_id = uuid4()

    records = [
        (key_a.id, tenant_a.id, "model-a", BASE, 10),
        (key_a.id, tenant_a.id, "model-a", BASE + timedelta(hours=1), 20),
        (key_b.id, tenant_a.id, "model-b", BASE + timedelta(hours=2), 50),
        (missing_key_id, tenant_a.id, "model-a", BASE + timedelta(hours=3), 5),
        (tenant_b_key.id, tenant_b.id, "model-a", BASE + timedelta(hours=4), 100),
    ]
    for index, (key_id, tenant_id, model_id, created_at, total) in enumerate(records):
        await seed_usage(
            container,
            tenant_id=tenant_id,
            api_key_id=key_id,
            model_id=model_id,
            created_at=created_at,
            prompt_tokens=total,
            completion_tokens=0,
            total_tokens=total,
            request_id=f"req-{index}",
        )
    return tenant_a, tenant_b, key_a, key_b, tenant_b_key, missing_key_id


async def test_usage_by_key_resolves_keys_and_orders_by_total(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant_a, _tenant_b, key_a, key_b, tenant_b_key, missing_key_id = await _seed_by_key(container)

    async with make_client(settings, container) as client:
        response = await client.get(
            "/api/v1/usage/by-key",
            headers=_auth(_master(settings)),
        )
        tenant_filtered = await client.get(
            f"/api/v1/usage/by-key?tenant_id={tenant_a.id}",
            headers=_auth(_master(settings)),
        )
        model_filtered = await client.get(
            "/api/v1/usage/by-key?model_id=model-a",
            headers=_auth(_master(settings)),
        )
        windowed = await client.get(
            f"/api/v1/usage/by-key?since={_iso(BASE)}&until={_iso(BASE + timedelta(hours=2))}",
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["api_key_id"] for item in items] == [
        str(tenant_b_key.id),
        str(key_b.id),
        str(key_a.id),
        str(missing_key_id),
    ]
    assert items[0]["total_tokens"] == 100

    by_id = {item["api_key_id"]: item for item in items}
    assert by_id[str(key_a.id)]["name"] == "key-a"
    assert by_id[str(key_a.id)]["key_prefix"] == "sk-gw-aaa"
    assert by_id[str(key_a.id)]["total_tokens"] == 30
    assert by_id[str(key_a.id)]["requests"] == 2
    assert by_id[str(key_b.id)]["name"] == "key-b"
    assert by_id[str(key_b.id)]["total_tokens"] == 50
    assert by_id[str(missing_key_id)]["name"] is None
    assert by_id[str(missing_key_id)]["key_prefix"] is None
    assert by_id[str(missing_key_id)]["total_tokens"] == 5

    assert {item["api_key_id"] for item in tenant_filtered.json()["items"]} == {
        str(key_a.id),
        str(key_b.id),
        str(missing_key_id),
    }

    assert {item["api_key_id"] for item in model_filtered.json()["items"]} == {
        str(key_a.id),
        str(missing_key_id),
        str(tenant_b_key.id),
    }

    windowed_items = windowed.json()["items"]
    assert {item["api_key_id"] for item in windowed_items} == {str(key_a.id)}
    key_a_window = next(item for item in windowed_items if item["api_key_id"] == str(key_a.id))
    assert key_a_window["total_tokens"] == 30


async def test_usage_by_key_validates_tenant_and_master_key(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    await _seed_by_key(container)

    async with make_client(settings, container) as client:
        unknown = await client.get(
            f"/api/v1/usage/by-key?tenant_id={uuid4()}",
            headers=_auth(_master(settings)),
        )
        missing_auth = await client.get("/api/v1/usage/by-key")

    assert unknown.status_code == 404
    assert _error(unknown)["code"] == "tenant_not_found"

    assert missing_auth.status_code == 401


async def _seed_series(container: Container) -> Tenant:
    tenant = await seed_tenant(container, name="series-tenant")
    key = await _create_key(container, tenant=tenant, name="series-key", prefix="sk-gw-sss")
    for index, created_at in enumerate(
        (
            datetime(2026, 1, 1, 10, 15, tzinfo=UTC),
            datetime(2026, 1, 1, 23, 30, tzinfo=UTC),
            datetime(2026, 1, 2, 0, 30, tzinfo=UTC),
        )
    ):
        await seed_usage(
            container,
            tenant_id=tenant.id,
            api_key_id=key.id,
            model_id="model-a",
            created_at=created_at,
            prompt_tokens=10,
            completion_tokens=0,
            total_tokens=10,
            request_id=f"series-{index}",
        )
    return tenant


async def test_usage_series_defaults_to_last_30_days_with_daily_buckets(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    await _seed_series(container)

    async with make_client(settings, container) as client:
        response = await client.get(
            "/api/v1/usage/series",
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["bucket"] == "day"
    points = body["points"]
    assert len(points) == 31
    assert points[0]["bucket_start"] == "2025-12-03T00:00:00Z"
    assert points[-1]["bucket_start"] == "2026-01-02T00:00:00Z"
    assert [point["bucket_start"] for point in points] == sorted(
        point["bucket_start"] for point in points
    )
    by_start = {point["bucket_start"]: point for point in points}
    assert by_start["2026-01-01T00:00:00Z"]["total_tokens"] == 20
    assert by_start["2026-01-01T00:00:00Z"]["requests"] == 2
    assert by_start["2026-01-02T00:00:00Z"]["total_tokens"] == 10
    assert by_start["2025-12-03T00:00:00Z"]["total_tokens"] == 0
    assert by_start["2025-12-03T00:00:00Z"]["requests"] == 0


async def test_usage_series_only_since_uses_now_as_until(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())

    async with make_client(settings, container) as client:
        response = await client.get(
            "/api/v1/usage/series?bucket=day&since=2025-12-20T00:00:00Z",
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    points = response.json()["points"]
    assert len(points) == 14
    assert points[0]["bucket_start"] == "2025-12-20T00:00:00Z"
    assert points[-1]["bucket_start"] == "2026-01-02T00:00:00Z"


async def test_usage_series_only_until_uses_30_days_before(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())

    async with make_client(settings, container) as client:
        response = await client.get(
            "/api/v1/usage/series?bucket=day&until=2026-01-02T00:00:00Z",
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    points = response.json()["points"]
    assert len(points) == 30
    assert points[0]["bucket_start"] == "2025-12-03T00:00:00Z"
    assert points[-1]["bucket_start"] == "2026-01-01T00:00:00Z"


async def test_usage_series_hour_bucket_and_validation(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await _seed_series(container)
    master = _auth(_master(settings))

    async with make_client(settings, container) as client:
        hourly = await client.get(
            "/api/v1/usage/series"
            "?bucket=hour&since=2026-01-01T10:00:00Z&until=2026-01-02T01:00:00Z",
            headers=master,
        )
        naive = await client.get(
            "/api/v1/usage/series?since=2026-01-01T00:00:00",
            headers=master,
        )
        inverted = await client.get(
            "/api/v1/usage/series?since=2026-01-03T00:00:00Z&until=2026-01-02T00:00:00Z",
            headers=master,
        )
        too_many = await client.get(
            "/api/v1/usage/series"
            "?bucket=hour&since=2026-01-01T00:00:00Z&until=2026-03-01T00:00:00Z",
            headers=master,
        )
        unknown = await client.get(
            f"/api/v1/usage/series?tenant_id={uuid4()}",
            headers=master,
        )
        empty = await client.get(
            "/api/v1/usage/series?model_id=missing-model",
            headers=master,
        )
        invalid_bucket = await client.get(
            "/api/v1/usage/series?bucket=week",
            headers=master,
        )
        tenant_series = await client.get(
            f"/api/v1/usage/series?tenant_id={tenant.id}",
            headers=master,
        )

    assert hourly.status_code == 200
    hourly_points = hourly.json()["points"]
    assert len(hourly_points) == 15
    assert all(point["bucket_start"].endswith(":00:00Z") for point in hourly_points)
    hourly_by_start = {point["bucket_start"]: point for point in hourly_points}
    assert hourly_by_start["2026-01-01T10:00:00Z"]["total_tokens"] == 10
    assert hourly_by_start["2026-01-01T23:00:00Z"]["total_tokens"] == 10
    assert hourly_by_start["2026-01-02T00:00:00Z"]["total_tokens"] == 10
    assert hourly_by_start["2026-01-01T12:00:00Z"]["total_tokens"] == 0

    assert naive.status_code == 400
    assert _error(naive)["code"] == "invalid_request_body"
    assert _error(naive)["param"] == "since"

    assert inverted.status_code == 400
    assert _error(inverted)["code"] == "invalid_request_body"

    assert too_many.status_code == 400
    assert _error(too_many)["param"] == "since"

    assert unknown.status_code == 404
    assert _error(unknown)["code"] == "tenant_not_found"

    assert empty.status_code == 200
    empty_points = empty.json()["points"]
    assert len(empty_points) == 31
    assert all(point["total_tokens"] == 0 for point in empty_points)
    assert all(point["requests"] == 0 for point in empty_points)

    assert invalid_bucket.status_code == 400
    assert _error(invalid_bucket)["code"] == "invalid_request_body"

    assert tenant_series.status_code == 200
    tenant_points = tenant_series.json()["points"]
    assert len(tenant_points) == 31
    nonzero = [point for point in tenant_points if point["total_tokens"] > 0]
    assert [point["bucket_start"] for point in nonzero] == [
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    ]


async def test_usage_series_zero_fills_sparse_days(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    await _seed_series(container)

    async with make_client(settings, container) as client:
        response = await client.get(
            "/api/v1/usage/series?bucket=day&since=2026-01-01T00:00:00Z&until=2026-01-04T00:00:00Z",
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    points = response.json()["points"]
    assert [point["bucket_start"] for point in points] == [
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
        "2026-01-03T00:00:00Z",
    ]
    assert [point["total_tokens"] for point in points] == [20, 10, 0]
    assert points[2]["requests"] == 0


async def test_usage_series_bucket_cap_uses_aligned_bucket_count(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    master = _auth(_master(settings))
    since = datetime(2020, 1, 1, tzinfo=UTC)
    exactly_1000 = since + timedelta(days=1000)
    over_1000 = since + timedelta(days=1001)

    async with make_client(settings, container) as client:
        allowed = await client.get(
            f"/api/v1/usage/series?bucket=day&since={_iso(since)}&until={_iso(exactly_1000)}",
            headers=master,
        )
        rejected = await client.get(
            f"/api/v1/usage/series?bucket=day&since={_iso(since)}&until={_iso(over_1000)}",
            headers=master,
        )

    assert allowed.status_code == 200
    assert len(allowed.json()["points"]) == 1000

    assert rejected.status_code == 400
    assert _error(rejected)["code"] == "invalid_request_body"
    assert _error(rejected)["param"] == "since"


async def test_usage_by_key_limit_returns_top_rows_and_validates_range(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    _tenant_a, _tenant_b, _key_a, key_b, tenant_b_key, _missing = await _seed_by_key(container)
    master = _auth(_master(settings))

    async with make_client(settings, container) as client:
        limited = await client.get(
            "/api/v1/usage/by-key?limit=2",
            headers=master,
        )
        zero = await client.get(
            "/api/v1/usage/by-key?limit=0",
            headers=master,
        )
        too_large = await client.get(
            "/api/v1/usage/by-key?limit=501",
            headers=master,
        )

    assert limited.status_code == 200
    body = limited.json()
    assert body["limit"] == 2
    assert [item["api_key_id"] for item in body["items"]] == [
        str(tenant_b_key.id),
        str(key_b.id),
    ]

    for response in (zero, too_large):
        assert response.status_code == 400
        assert _error(response)["code"] == "invalid_request_body"
