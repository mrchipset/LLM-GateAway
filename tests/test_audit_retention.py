from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from llm_gateway.config import Environment, Settings
from llm_gateway.container import Container
from llm_gateway.metrics import build_metrics, install_metrics, reset_metrics_for_tests
from llm_gateway.services.audit_retention import AuditRetentionService
from llm_gateway.storage.memory import InMemoryAuditRepository
from llm_gateway.storage.repositories import (
    AuditRequestRecord,
    AuditSessionRecord,
    Tenant,
)
from support import FrozenClock

MASTER_KEY = "test-master-key-0123456789abcdef"
NOW = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def _settings(*, audit_retention_days: int = 30) -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": MASTER_KEY,
            "audit_retention_days": audit_retention_days,
        }
    )


def _service(container: Container, settings: Settings) -> AuditRetentionService:
    return AuditRetentionService(
        settings=settings,
        audit=container.audit,
        tenants=container.tenants,
        clock=FrozenClock(NOW),
    )


async def _tenant(
    container: Container,
    *,
    name: str,
    audit_retention_days: int | None = None,
    tenant_id: UUID | None = None,
) -> Tenant:
    tenant = Tenant(
        id=tenant_id or uuid4(),
        name=name,
        created_at=NOW,
        audit_retention_days=audit_retention_days,
    )
    return await container.tenants.create_tenant(tenant)


async def _seed_turn(
    container: Container,
    *,
    tenant: Tenant,
    created_at: datetime,
    request_id: str | None = None,
    session_id: UUID | None = None,
    session_last_seen_at: datetime | None = None,
) -> AuditSessionRecord:
    request_id = request_id or f"req-{uuid4()}"
    session = AuditSessionRecord(
        id=session_id or uuid4(),
        tenant_id=tenant.id,
        external_session_id=None,
        api_key_id=uuid4(),
        api_key_prefix="sk-gw",
        root_request_id=request_id,
        model_id="fake-model",
        provider="fake",
        title_preview="hello",
        created_at=created_at,
        last_seen_at=session_last_seen_at if session_last_seen_at is not None else created_at,
        request_count=1,
        total_tokens=5,
    )
    request = AuditRequestRecord(
        request_id=request_id,
        session_id=session.id,
        parent_request_id=None,
        tenant_id=tenant.id,
        api_key_id=session.api_key_id,
        turn_index=0,
        match_method="new",
        change_type="initial",
        model_id="fake-model",
        provider="fake",
        is_stream=False,
        request_messages=[{"role": "user", "content": "hello"}],
        message_hashes=["hash-1"],
        request_params={"model": "fake-model"},
        response_content="reply",
        response_tool_calls=None,
        response_content_hash=None,
        finish_reason="stop",
        status="completed",
        prompt_tokens=3,
        completion_tokens=2,
        cached_tokens=0,
        total_tokens=5,
        truncated=False,
        created_at=created_at,
    )
    await container.audit.record_turn(session=session, request=request, diff=None)
    return session


async def _request_count(container: Container, tenant: Tenant) -> int:
    return await container.audit.count_requests(tenant_id=tenant.id, since=None, until=None)


@pytest.fixture(name="metric_reader")
def metric_reader_fixture() -> Iterator[InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    install_metrics(build_metrics(provider.get_meter("test")))
    try:
        yield reader
    finally:
        reset_metrics_for_tests()
        provider.shutdown()


def _metric_points(reader: InMemoryMetricReader, name: str) -> list[Any]:
    data = reader.get_metrics_data()
    if data is None:
        return []
    points: list[Any] = []
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == name:
                    points.extend(
                        metric.data.data_points  # pyright: ignore[reportAttributeAccessIssue]
                    )
    return points


def _counter_total(reader: InMemoryMetricReader, name: str, **labels: str) -> int:
    total = 0
    for point in _metric_points(reader, name):
        attributes = dict(point.attributes)
        if all(attributes.get(key) == value for key, value in labels.items()):
            total += int(point.value)
    return total


class _FailingDeleteRepository(InMemoryAuditRepository):
    def __init__(self, failing_tenant_id: UUID) -> None:
        super().__init__()
        self._failing_tenant_id = failing_tenant_id

    async def delete_requests_before(
        self, *, tenant_id: UUID, cutoff: datetime, batch_size: int
    ) -> int:
        if tenant_id == self._failing_tenant_id:
            raise RuntimeError("audit storage unavailable")
        return await super().delete_requests_before(
            tenant_id=tenant_id, cutoff=cutoff, batch_size=batch_size
        )


async def test_tenant_override_wins_over_global_default(
    make_container: Callable[..., Container],
) -> None:
    settings = _settings(audit_retention_days=30)
    container = make_container(settings, clock=FrozenClock(NOW))
    override = await _tenant(container, name="override", audit_retention_days=1)
    inheriting = await _tenant(container, name="inheriting")
    old = NOW - 10 * DAY
    await _seed_turn(container, tenant=override, created_at=old)
    await _seed_turn(container, tenant=inheriting, created_at=old)

    report = await _service(container, settings).run()

    assert await _request_count(container, override) == 0
    assert await _request_count(container, inheriting) == 1
    by_tenant = {outcome.tenant_id: outcome for outcome in report.outcomes}
    assert by_tenant[override.id].cutoff == NOW - DAY
    assert by_tenant[inheriting.id].cutoff == NOW - 30 * DAY


async def test_legal_hold_zero_keeps_every_row(
    make_container: Callable[..., Container],
) -> None:
    settings = _settings(audit_retention_days=30)
    container = make_container(settings, clock=FrozenClock(NOW))
    tenant = await _tenant(container, name="legal-hold", audit_retention_days=0)
    await _seed_turn(container, tenant=tenant, created_at=NOW - 365 * DAY)

    report = await _service(container, settings).run()

    assert await _request_count(container, tenant) == 1
    assert len(report.outcomes) == 1
    outcome = report.outcomes[0]
    assert outcome.outcome == "skipped"
    assert outcome.reason == "legal_hold"
    assert outcome.cutoff is None


async def test_dry_run_reports_count_without_deleting(
    make_container: Callable[..., Container],
    metric_reader: InMemoryMetricReader,
) -> None:
    settings = _settings(audit_retention_days=30)
    container = make_container(settings, clock=FrozenClock(NOW))
    tenant = await _tenant(container, name="dry-run")
    for _ in range(3):
        await _seed_turn(container, tenant=tenant, created_at=NOW - 60 * DAY)

    report = await _service(container, settings).run(dry_run=True)

    assert report.dry_run is True
    assert report.requests_deleted == 3
    assert report.sessions_deleted == 0
    assert report.outcomes[0].dry_run is True
    assert await _request_count(container, tenant) == 3
    assert _counter_total(metric_reader, "gateway_audit_cleanup_rows") == 0


async def test_batches_delete_all_old_requests_when_batch_is_smaller(
    make_container: Callable[..., Container],
) -> None:
    settings = _settings(audit_retention_days=30)
    container = make_container(settings, clock=FrozenClock(NOW))
    tenant = await _tenant(container, name="batched")
    for index in range(7):
        await _seed_turn(
            container,
            tenant=tenant,
            created_at=NOW - (40 + index) * DAY,
            request_id=f"req-batch-{index}",
        )

    report = await _service(container, settings).run(batch_size=3, max_batches=10)

    assert report.requests_deleted == 7
    assert report.truncated is False
    assert await _request_count(container, tenant) == 0


async def test_max_batches_truncates_and_reports(
    make_container: Callable[..., Container],
) -> None:
    settings = _settings(audit_retention_days=30)
    container = make_container(settings, clock=FrozenClock(NOW))
    tenant = await _tenant(container, name="truncated")
    for index in range(7):
        await _seed_turn(
            container,
            tenant=tenant,
            created_at=NOW - (40 + index) * DAY,
            request_id=f"req-trunc-{index}",
        )

    report = await _service(container, settings).run(batch_size=3, max_batches=1)

    assert report.requests_deleted == 3
    assert report.truncated is True
    assert await _request_count(container, tenant) == 4


async def test_orphan_sessions_removed_but_sessions_with_requests_survive(
    make_container: Callable[..., Container],
) -> None:
    settings = _settings(audit_retention_days=30)
    container = make_container(settings, clock=FrozenClock(NOW))
    tenant = await _tenant(container, name="sessions")

    orphan = await _seed_turn(container, tenant=tenant, created_at=NOW - 60 * DAY)
    survivor = await _seed_turn(
        container,
        tenant=tenant,
        created_at=NOW - 60 * DAY,
        session_last_seen_at=NOW - 60 * DAY,
    )
    # A newer request keeps its session alive even though the session row looks old.
    await _seed_turn(
        container,
        tenant=tenant,
        created_at=NOW,
        session_id=survivor.id,
        session_last_seen_at=NOW - 60 * DAY,
    )

    report = await _service(container, settings).run()

    assert report.sessions_deleted == 1
    assert await container.audit.get_session(session_id=orphan.id) is None
    assert await container.audit.get_session(session_id=survivor.id) is not None


async def test_failing_repository_marks_one_tenant_failed_and_continues(
    make_container: Callable[..., Container],
    metric_reader: InMemoryMetricReader,
) -> None:
    settings = _settings(audit_retention_days=30)
    failing_id = uuid4()
    container = make_container(
        settings,
        clock=FrozenClock(NOW),
        audit=_FailingDeleteRepository(failing_id),
    )
    failing_tenant = await _tenant(
        container, name="failing", audit_retention_days=30, tenant_id=failing_id
    )
    healthy = await _tenant(container, name="healthy", audit_retention_days=30)
    await _seed_turn(container, tenant=failing_tenant, created_at=NOW - 60 * DAY)
    await _seed_turn(container, tenant=healthy, created_at=NOW - 60 * DAY)

    report = await _service(container, settings).run(tenant_ids=[failing_tenant.id, healthy.id])

    outcomes = {outcome.tenant_id: outcome for outcome in report.outcomes}
    assert outcomes[failing_tenant.id].outcome == "failed"
    assert outcomes[healthy.id].outcome == "completed"
    assert await _request_count(container, healthy) == 0
    assert await _request_count(container, failing_tenant) == 1
    assert report.failed == 1
    assert _counter_total(metric_reader, "gateway_audit_cleanup_failures", stage="requests") == 1
