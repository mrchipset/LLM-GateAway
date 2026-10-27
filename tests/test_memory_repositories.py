from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from llm_gateway.providers.base import ProviderName
from llm_gateway.storage.memory import (
    InMemoryApiKeyRepository,
    InMemoryAuditRepository,
    InMemoryModelRepository,
    InMemoryTenantRepository,
)
from llm_gateway.storage.repositories import (
    ApiKeyRecord,
    AuditPrefixRecord,
    AuditRequestRecord,
    AuditSessionFilters,
    AuditSessionRecord,
    AuditTurnDiffRecord,
    DuplicateApiKeyError,
    DuplicateModelError,
    DuplicateTenantError,
    ModelConfig,
    Tenant,
)

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
TENANT_ID = uuid4()
OTHER_TENANT_ID = uuid4()


def _tenant(index: int) -> Tenant:
    return Tenant(
        id=uuid4(),
        name=f"tenant-{index}",
        created_at=BASE + timedelta(seconds=index),
    )


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _model(index: int) -> ModelConfig:
    return ModelConfig(
        id=f"model-{index}",
        provider=ProviderName.FAKE,
        upstream_model=f"upstream-{index}",
        created_at=BASE + timedelta(seconds=index),
    )


def _key(index: int, *, key_hash: str | None = None, tenant_id: UUID = TENANT_ID) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        name=f"key-{index}",
        key_hash=key_hash if key_hash is not None else _hash(f"key-{index}"),
        key_prefix=f"sk-gw-{index:06d}",
        created_at=BASE + timedelta(seconds=index),
    )


async def test_model_create_get_list_delete() -> None:
    repository = InMemoryModelRepository()
    model = _model(1)

    created = await repository.create_model(model)

    assert created == model
    assert await repository.get_model(model.id) == model
    items, total = await repository.list_models(limit=10, offset=0)
    assert list(items) == [model]
    assert total == 1

    assert await repository.delete_model(model.id) is True
    assert await repository.get_model(model.id) is None
    assert await repository.delete_model(model.id) is False


async def test_model_duplicate_create_raises() -> None:
    repository = InMemoryModelRepository()
    model = _model(1)
    await repository.create_model(model)

    with pytest.raises(DuplicateModelError, match="model 'model-1' already exists"):
        await repository.create_model(model)


async def test_model_list_is_newest_first_with_pagination() -> None:
    repository = InMemoryModelRepository()
    for index in range(5):
        await repository.create_model(_model(index))

    items, total = await repository.list_models(limit=2, offset=1)

    assert total == 5
    assert [item.id for item in items] == ["model-3", "model-2"]


@pytest.mark.parametrize(
    ("limit", "offset", "message"),
    [(0, 0, "limit must be >= 1"), (-1, 0, "limit must be >= 1"), (1, -1, "offset must be >= 0")],
)
async def test_model_list_rejects_invalid_pagination(limit: int, offset: int, message: str) -> None:
    repository = InMemoryModelRepository()

    with pytest.raises(ValueError, match=message):
        await repository.list_models(limit=limit, offset=offset)


async def test_api_key_create_and_get_by_id_and_hash() -> None:
    repository = InMemoryApiKeyRepository()
    key = _key(1)

    created = await repository.create_key(key)

    assert created == key
    assert await repository.get_key(key.id) == key
    assert await repository.get_key_by_hash(key.key_hash) == key
    assert await repository.get_key(uuid4()) is None
    assert await repository.get_key_by_hash("missing-hash") is None


async def test_api_key_duplicate_hash_raises() -> None:
    repository = InMemoryApiKeyRepository()
    shared_hash = _hash("shared")
    await repository.create_key(_key(1, key_hash=shared_hash))

    with pytest.raises(DuplicateApiKeyError):
        await repository.create_key(_key(2, key_hash=shared_hash))


async def test_api_key_revoke_transitions_once() -> None:
    repository = InMemoryApiKeyRepository()
    key = _key(1)
    await repository.create_key(key)

    assert await repository.revoke_key(key.id, BASE) is True
    revoked = await repository.get_key(key.id)
    assert revoked is not None
    assert revoked.revoked_at == BASE
    assert await repository.revoke_key(key.id, BASE) is False


async def test_api_key_touch_last_used_updates_record() -> None:
    repository = InMemoryApiKeyRepository()
    key = _key(1)
    await repository.create_key(key)

    await repository.touch_last_used(key.id, BASE)

    updated = await repository.get_key(key.id)
    assert updated is not None
    assert updated.last_used_at == BASE


async def test_api_key_touch_last_used_raises_for_missing_key() -> None:
    repository = InMemoryApiKeyRepository()

    with pytest.raises(KeyError):
        await repository.touch_last_used(uuid4(), BASE)


async def test_api_key_list_is_newest_first_with_pagination() -> None:
    repository = InMemoryApiKeyRepository()
    for index in range(5):
        await repository.create_key(_key(index))

    items, total = await repository.list_keys(limit=2, offset=1)

    assert total == 5
    assert [item.name for item in items] == ["key-3", "key-2"]


async def test_model_list_enabled_only_filters_before_pagination() -> None:
    repository = InMemoryModelRepository()
    await repository.create_model(_model(0))
    await repository.create_model(_model(1))
    await repository.create_model(
        ModelConfig(
            id="model-disabled",
            provider=ProviderName.FAKE,
            upstream_model="upstream-disabled",
            created_at=BASE + timedelta(seconds=2),
            enabled=False,
        )
    )

    items, total = await repository.list_models(limit=10, offset=0, enabled_only=True)

    assert total == 2
    assert {item.id for item in items} == {"model-0", "model-1"}

    page, filtered_total = await repository.list_models(limit=1, offset=0, enabled_only=True)

    assert filtered_total == 2
    assert [item.id for item in page] == ["model-1"]


def test_model_rejects_naive_created_at() -> None:
    with pytest.raises(ValueError, match="created_at"):
        ModelConfig(
            id="model-1",
            provider=ProviderName.FAKE,
            upstream_model="upstream-1",
            created_at=datetime(2026, 1, 1, 12, 0),  # noqa: DTZ001 - naive input under test
        )


def test_model_rejects_blank_id() -> None:
    with pytest.raises(ValueError, match="id"):
        ModelConfig(
            id="   ",
            provider=ProviderName.FAKE,
            upstream_model="upstream-1",
            created_at=BASE,
        )


def test_api_key_rejects_naive_expires_at() -> None:
    with pytest.raises(ValueError, match="expires_at"):
        ApiKeyRecord(
            id=uuid4(),
            tenant_id=TENANT_ID,
            name="key-1",
            key_hash=_hash("key-1"),
            key_prefix="sk-gw-000001",
            created_at=BASE,
            expires_at=datetime(2026, 1, 2, 12, 0),  # noqa: DTZ001 - naive input under test
        )


def test_api_key_rejects_naive_last_used_at() -> None:
    with pytest.raises(ValueError, match="last_used_at"):
        ApiKeyRecord(
            id=uuid4(),
            tenant_id=TENANT_ID,
            name="key-1",
            key_hash=_hash("key-1"),
            key_prefix="sk-gw-000001",
            created_at=BASE,
            last_used_at=datetime(2026, 1, 2, 12, 0),  # noqa: DTZ001 - naive input under test
        )


def test_api_key_rejects_invalid_hash() -> None:
    with pytest.raises(ValueError, match="key_hash"):
        _key(1, key_hash="not-a-hash")


async def test_tenant_create_get_and_list() -> None:
    repository = InMemoryTenantRepository()
    tenant = _tenant(1)

    created = await repository.create_tenant(tenant)

    assert created == tenant
    assert await repository.get_tenant(tenant.id) == tenant
    assert await repository.get_tenant(uuid4()) is None
    items, total = await repository.list_tenants(limit=10, offset=0)
    assert list(items) == [tenant]
    assert total == 1


async def test_tenant_duplicate_name_raises() -> None:
    repository = InMemoryTenantRepository()
    await repository.create_tenant(_tenant(1))

    duplicate = Tenant(id=uuid4(), name="tenant-1", created_at=BASE)
    with pytest.raises(DuplicateTenantError, match="tenant 'tenant-1' already exists"):
        await repository.create_tenant(duplicate)


async def test_tenant_duplicate_id_raises() -> None:
    repository = InMemoryTenantRepository()
    existing = _tenant(1)
    await repository.create_tenant(existing)

    conflicting = Tenant(id=existing.id, name="other", created_at=BASE)
    with pytest.raises(DuplicateTenantError, match="tenant 'other' already exists"):
        await repository.create_tenant(conflicting)


async def test_tenant_names_are_case_sensitive() -> None:
    repository = InMemoryTenantRepository()
    await repository.create_tenant(Tenant(id=uuid4(), name="Acme", created_at=BASE))

    created = await repository.create_tenant(Tenant(id=uuid4(), name="acme", created_at=BASE))

    assert created.name == "acme"


async def test_tenant_list_is_newest_first_with_pagination() -> None:
    repository = InMemoryTenantRepository()
    for index in range(5):
        await repository.create_tenant(_tenant(index))

    items, total = await repository.list_tenants(limit=2, offset=1)

    assert total == 5
    assert [item.name for item in items] == ["tenant-3", "tenant-2"]


@pytest.mark.parametrize(
    ("limit", "offset", "message"),
    [(0, 0, "limit must be >= 1"), (-1, 0, "limit must be >= 1"), (1, -1, "offset must be >= 0")],
)
async def test_tenant_list_rejects_invalid_pagination(
    limit: int, offset: int, message: str
) -> None:
    repository = InMemoryTenantRepository()

    with pytest.raises(ValueError, match=message):
        await repository.list_tenants(limit=limit, offset=offset)


async def test_api_key_list_filters_by_tenant_before_pagination() -> None:
    repository = InMemoryApiKeyRepository()
    await repository.create_key(_key(0, tenant_id=TENANT_ID))
    await repository.create_key(_key(1, tenant_id=TENANT_ID))
    await repository.create_key(_key(2, tenant_id=OTHER_TENANT_ID))

    items, total = await repository.list_keys(limit=10, offset=0, tenant_id=OTHER_TENANT_ID)

    assert total == 1
    assert [item.name for item in items] == ["key-2"]

    page, filtered_total = await repository.list_keys(limit=1, offset=1, tenant_id=TENANT_ID)

    assert filtered_total == 2
    assert [item.name for item in page] == ["key-0"]


def _audit_session(
    index: int,
    *,
    tenant_id: UUID = TENANT_ID,
    api_key_id: UUID | None = None,
    external_session_id: str | None = None,
    model_id: str = "model-1",
    title_preview: str | None = None,
    created_at: datetime | None = None,
    last_seen_at: datetime | None = None,
    request_count: int = 1,
    total_tokens: int = 0,
) -> AuditSessionRecord:
    created = created_at if created_at is not None else BASE + timedelta(seconds=index)
    return AuditSessionRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        external_session_id=external_session_id,
        api_key_id=api_key_id if api_key_id is not None else uuid4(),
        api_key_prefix="sk-gw-audit",
        root_request_id=f"root-{index}",
        model_id=model_id,
        provider="fake",
        title_preview=title_preview if title_preview is not None else f"title-{index}",
        created_at=created,
        last_seen_at=last_seen_at if last_seen_at is not None else created,
        request_count=request_count,
        total_tokens=total_tokens,
    )


def _audit_request(
    index: int,
    *,
    session_id: UUID,
    tenant_id: UUID = TENANT_ID,
    api_key_id: UUID | None = None,
    created_at: datetime | None = None,
    turn_index: int | None = None,
    total_tokens: int = 15,
    request_id: str | None = None,
) -> AuditRequestRecord:
    return AuditRequestRecord(
        request_id=request_id if request_id is not None else f"req-{index}",
        session_id=session_id,
        parent_request_id=None,
        tenant_id=tenant_id,
        api_key_id=api_key_id if api_key_id is not None else uuid4(),
        turn_index=turn_index if turn_index is not None else index,
        match_method="new",
        change_type="new_turn",
        model_id="model-1",
        provider="fake",
        is_stream=False,
        request_messages=[{"role": "user", "content": f"hi-{index}"}],
        message_hashes=[_hash(f"msg-{index}")],
        request_params={"temperature": 0.2},
        response_content=f"answer-{index}",
        response_tool_calls=None,
        response_content_hash=_hash(f"answer-{index}"),
        finish_reason="stop",
        status="success",
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=0,
        total_tokens=total_tokens,
        truncated=False,
        created_at=created_at if created_at is not None else BASE + timedelta(seconds=index),
    )


def _audit_diff(
    index: int,
    *,
    request_id: str,
    previous_request_id: str | None = None,
) -> AuditTurnDiffRecord:
    return AuditTurnDiffRecord(
        request_id=request_id,
        previous_request_id=previous_request_id,
        change_type="new_turn",
        common_prefix=0,
        added_messages=[{"role": "user", "content": f"hi-{index}"}],
        modified_messages=[],
        removed_messages=[],
        parameter_changes={"temperature": {"from": None, "to": 0.2}},
        usage_delta={"total_tokens": 15},
        response_change={"content_changed": True},
        created_at=BASE + timedelta(seconds=index),
    )


async def test_audit_record_turn_inserts_then_increments_session_stats() -> None:
    repository = InMemoryAuditRepository()
    session = _audit_session(0, request_count=1, total_tokens=15)
    first = _audit_request(0, session_id=session.id)
    diff = _audit_diff(0, request_id=first.request_id)

    await repository.record_turn(session=session, request=first, diff=diff)

    stored = await repository.get_session(session_id=session.id)
    assert stored == session
    assert await repository.get_request(request_id=first.request_id) == first
    assert await repository.get_diff(request_id=first.request_id) == diff

    later = _audit_request(
        1,
        session_id=session.id,
        created_at=BASE + timedelta(seconds=30),
        total_tokens=7,
    )
    await repository.record_turn(session=session, request=later, diff=None)

    updated = await repository.get_session(session_id=session.id)
    assert updated is not None
    assert updated.request_count == 2
    assert updated.total_tokens == 22
    assert updated.last_seen_at == BASE + timedelta(seconds=30)
    assert updated.created_at == session.created_at
    assert updated.root_request_id == session.root_request_id
    assert updated.model_id == session.model_id
    assert updated.provider == session.provider
    assert updated.title_preview == session.title_preview


async def test_audit_external_session_id_is_unique_per_tenant() -> None:
    repository = InMemoryAuditRepository()
    session = _audit_session(0, tenant_id=TENANT_ID, external_session_id="ext-1")
    await repository.record_turn(
        session=session,
        request=_audit_request(0, session_id=session.id),
        diff=None,
    )

    found = await repository.get_session_by_external_id(
        tenant_id=TENANT_ID, external_session_id="ext-1"
    )
    assert found == session

    other = _audit_session(1, tenant_id=OTHER_TENANT_ID, external_session_id="ext-1")
    await repository.record_turn(
        session=other,
        request=_audit_request(1, session_id=other.id, tenant_id=OTHER_TENANT_ID),
        diff=None,
    )

    duplicate = _audit_session(2, tenant_id=TENANT_ID, external_session_id="ext-1")
    with pytest.raises(ValueError, match="external session"):
        await repository.record_turn(
            session=duplicate,
            request=_audit_request(2, session_id=duplicate.id),
            diff=None,
        )

    assert await repository.get_session(session_id=duplicate.id) is None


async def test_audit_list_sessions_filters_q_and_pagination() -> None:
    repository = InMemoryAuditRepository()
    sessions = [
        _audit_session(
            0,
            tenant_id=TENANT_ID,
            model_id="model-a",
            title_preview="Alpha prompt",
            last_seen_at=BASE,
        ),
        _audit_session(
            1,
            tenant_id=TENANT_ID,
            model_id="model-b",
            title_preview="beta prompt",
            last_seen_at=BASE + timedelta(minutes=1),
        ),
        _audit_session(
            2,
            tenant_id=OTHER_TENANT_ID,
            model_id="model-a",
            title_preview="gamma prompt",
            last_seen_at=BASE + timedelta(minutes=2),
        ),
    ]
    for index, session in enumerate(sessions):
        await repository.record_turn(
            session=session,
            request=_audit_request(index, session_id=session.id, tenant_id=session.tenant_id),
            diff=None,
        )

    page = await repository.list_sessions(
        filters=AuditSessionFilters(tenant_id=TENANT_ID), limit=10, offset=0
    )
    assert page.total == 2
    assert [item.id for item in page.items] == [sessions[1].id, sessions[0].id]

    by_model = await repository.list_sessions(
        filters=AuditSessionFilters(tenant_id=TENANT_ID, model_id="model-a"),
        limit=10,
        offset=0,
    )
    assert [item.id for item in by_model.items] == [sessions[0].id]

    by_title = await repository.list_sessions(
        filters=AuditSessionFilters(tenant_id=None, q="ALPHA"), limit=10, offset=0
    )
    assert [item.id for item in by_title.items] == [sessions[0].id]

    by_root = await repository.list_sessions(
        filters=AuditSessionFilters(tenant_id=None, q="root-2"), limit=10, offset=0
    )
    assert [item.id for item in by_root.items] == [sessions[2].id]

    by_id = await repository.list_sessions(
        filters=AuditSessionFilters(tenant_id=None, q=str(sessions[1].id)[:8]),
        limit=10,
        offset=0,
    )
    assert [item.id for item in by_id.items] == [sessions[1].id]

    windowed = await repository.list_sessions(
        filters=AuditSessionFilters(
            tenant_id=None, since=BASE + timedelta(seconds=30), until=BASE + timedelta(minutes=2)
        ),
        limit=10,
        offset=0,
    )
    assert [item.id for item in windowed.items] == [sessions[1].id]

    second_page = await repository.list_sessions(
        filters=AuditSessionFilters(tenant_id=None), limit=1, offset=1
    )
    assert second_page.total == 3
    assert [item.id for item in second_page.items] == [sessions[1].id]


async def test_audit_list_session_requests_and_latest_request() -> None:
    repository = InMemoryAuditRepository()
    session = _audit_session(0)
    first = _audit_request(0, session_id=session.id, api_key_id=session.api_key_id, turn_index=0)
    second = _audit_request(
        1,
        session_id=session.id,
        api_key_id=session.api_key_id,
        turn_index=1,
        created_at=BASE + timedelta(seconds=5),
    )
    await repository.record_turn(session=session, request=first, diff=None)
    await repository.record_turn(session=session, request=second, diff=None)

    requests = await repository.list_session_requests(session_id=session.id)

    assert [item.request_id for item in requests] == [first.request_id, second.request_id]
    latest = await repository.get_latest_request(session_id=session.id)
    assert latest == second
    recent = await repository.recent_prefix_requests(
        tenant_id=TENANT_ID,
        api_key_id=session.api_key_id,
        since=BASE,
        limit=1,
    )
    assert recent == [
        AuditPrefixRecord(
            request_id=second.request_id,
            session_id=session.id,
            turn_index=second.turn_index,
            message_hashes=second.message_hashes,
            created_at=second.created_at,
        )
    ]


async def test_audit_get_diffs_round_trips_and_unknown_returns_none() -> None:
    repository = InMemoryAuditRepository()
    session = _audit_session(0)
    first = _audit_request(0, session_id=session.id, turn_index=0)
    second = _audit_request(1, session_id=session.id, turn_index=1)
    first_diff = _audit_diff(0, request_id=first.request_id)
    second_diff = _audit_diff(1, request_id=second.request_id, previous_request_id=first.request_id)
    await repository.record_turn(session=session, request=first, diff=first_diff)
    await repository.record_turn(session=session, request=second, diff=second_diff)

    diffs = await repository.get_diffs(request_ids=[first.request_id, second.request_id, "missing"])
    assert diffs == {first.request_id: first_diff, second.request_id: second_diff}
    assert await repository.get_diffs(request_ids=[]) == {}

    assert await repository.get_session(session_id=uuid4()) is None
    assert await repository.get_request(request_id="missing") is None
    assert await repository.get_diff(request_id="missing") is None
    assert await repository.get_latest_request(session_id=uuid4()) is None
    assert (
        await repository.get_session_by_external_id(
            tenant_id=TENANT_ID, external_session_id="missing"
        )
        is None
    )


async def test_audit_recent_prefix_requests_filters_tenant_and_api_key() -> None:
    repository = InMemoryAuditRepository()
    key_a = uuid4()
    key_b = uuid4()
    session_a = _audit_session(0, api_key_id=key_a)
    session_b = _audit_session(1, api_key_id=key_b)
    session_other = _audit_session(2, tenant_id=OTHER_TENANT_ID, api_key_id=key_a)
    first = _audit_request(
        0, session_id=session_a.id, api_key_id=key_a, created_at=BASE, request_id="req-a-0"
    )
    second = _audit_request(
        1,
        session_id=session_a.id,
        api_key_id=key_a,
        created_at=BASE + timedelta(seconds=2),
        request_id="req-a-1",
    )
    other_key = _audit_request(2, session_id=session_b.id, api_key_id=key_b)
    other_tenant = _audit_request(
        3, session_id=session_other.id, tenant_id=OTHER_TENANT_ID, api_key_id=key_a
    )
    for session, request in (
        (session_a, first),
        (session_a, second),
        (session_b, other_key),
        (session_other, other_tenant),
    ):
        await repository.record_turn(session=session, request=request, diff=None)

    records = await repository.recent_prefix_requests(
        tenant_id=TENANT_ID, api_key_id=key_a, since=BASE, limit=10
    )

    assert [record.request_id for record in records] == ["req-a-1", "req-a-0"]
    assert records[0].session_id == session_a.id
    assert records[0].message_hashes == second.message_hashes
    assert all(isinstance(record, AuditPrefixRecord) for record in records)

    limited = await repository.recent_prefix_requests(
        tenant_id=TENANT_ID, api_key_id=key_a, since=BASE, limit=1
    )
    assert [record.request_id for record in limited] == ["req-a-1"]

    with pytest.raises(ValueError, match="limit must be >= 1"):
        await repository.recent_prefix_requests(
            tenant_id=TENANT_ID, api_key_id=key_a, since=BASE, limit=0
        )


async def test_audit_ensure_session_is_idempotent_and_converges() -> None:
    repository = InMemoryAuditRepository()
    session = _audit_session(0, external_session_id="ext-1")

    first = await repository.ensure_session(session=session)
    second = await repository.ensure_session(session=session)

    assert first == session
    assert second == session
    assert await repository.get_session(session_id=session.id) == session

    conflicting = _audit_session(1, external_session_id="ext-1")
    converged = await repository.ensure_session(session=conflicting)

    assert converged.id == session.id
    assert await repository.get_session(session_id=conflicting.id) is None

    racers = [_audit_session(index + 10, external_session_id="race") for index in range(5)]
    results = await asyncio.gather(*(repository.ensure_session(session=racer) for racer in racers))

    assert len({record.id for record in results}) == 1
    assert (
        await repository.get_session_by_external_id(tenant_id=TENANT_ID, external_session_id="race")
        == results[0]
    )


async def test_audit_q_matches_non_root_request_id_prefix() -> None:
    repository = InMemoryAuditRepository()
    session = _audit_session(0, title_preview="no match title")
    root = _audit_request(0, session_id=session.id, turn_index=0, request_id="root-0")
    branch = _audit_request(
        1,
        session_id=session.id,
        turn_index=1,
        created_at=BASE + timedelta(seconds=5),
        request_id="branch-abc",
    )
    await repository.record_turn(session=session, request=root, diff=None)
    await repository.record_turn(session=session, request=branch, diff=None)

    page = await repository.list_sessions(
        filters=AuditSessionFilters(tenant_id=TENANT_ID, q="branch"), limit=10, offset=0
    )

    assert [item.id for item in page.items] == [session.id]
    assert page.total == 1


async def test_audit_list_session_requests_tiebreaks_branch_order() -> None:
    repository = InMemoryAuditRepository()
    session = _audit_session(0)
    root = _audit_request(0, session_id=session.id, turn_index=0, request_id="root-0")
    shared_time = BASE + timedelta(seconds=5)
    later_id = _audit_request(
        1,
        session_id=session.id,
        turn_index=1,
        created_at=shared_time,
        request_id="req-b",
    )
    earlier_id = _audit_request(
        2,
        session_id=session.id,
        turn_index=1,
        created_at=shared_time,
        request_id="req-a",
    )
    await repository.record_turn(session=session, request=root, diff=None)
    await repository.record_turn(session=session, request=later_id, diff=None)
    await repository.record_turn(session=session, request=earlier_id, diff=None)

    ordered = await repository.list_session_requests(session_id=session.id)

    assert [request.request_id for request in ordered] == [
        "root-0",
        "req-a",
        "req-b",
    ]


async def test_audit_record_turn_reconciles_placeholder_metadata() -> None:
    repository = InMemoryAuditRepository()
    placeholder = _audit_session(
        0,
        model_id="failed-model",
        title_preview="failed title",
        created_at=BASE,
        last_seen_at=BASE,
        request_count=0,
        total_tokens=0,
    )
    await repository.ensure_session(session=placeholder)

    succeeded_at = BASE + timedelta(seconds=30)
    incoming = replace(
        placeholder,
        root_request_id="root-succeeded",
        model_id="model-succeeded",
        provider="openai",
        title_preview="succeeded title",
        created_at=succeeded_at,
        last_seen_at=succeeded_at,
    )
    request = _audit_request(
        0,
        session_id=placeholder.id,
        created_at=succeeded_at,
        total_tokens=9,
    )

    await repository.record_turn(session=incoming, request=request, diff=None)

    stored = await repository.get_session(session_id=placeholder.id)
    assert stored is not None
    assert stored.request_count == 1
    assert stored.total_tokens == 9
    assert stored.root_request_id == "root-succeeded"
    assert stored.model_id == "model-succeeded"
    assert stored.provider == "openai"
    assert stored.title_preview == "succeeded title"
    assert stored.created_at == succeeded_at
    assert stored.last_seen_at == succeeded_at


async def test_audit_list_sessions_hides_placeholder_until_first_turn() -> None:
    repository = InMemoryAuditRepository()
    placeholder = _audit_session(0, request_count=0)
    await repository.ensure_session(session=placeholder)

    empty = await repository.list_sessions(filters=AuditSessionFilters(), limit=10, offset=0)

    assert empty.items == []
    assert empty.total == 0

    request = _audit_request(0, session_id=placeholder.id)
    await repository.record_turn(session=placeholder, request=request, diff=None)

    listed = await repository.list_sessions(filters=AuditSessionFilters(), limit=10, offset=0)

    assert [item.id for item in listed.items] == [placeholder.id]
    assert listed.total == 1


async def test_audit_list_session_request_summaries_orders_without_content() -> None:
    repository = InMemoryAuditRepository()
    session = _audit_session(0)
    root = _audit_request(0, session_id=session.id, turn_index=0, request_id="root-0")
    shared_time = BASE + timedelta(seconds=5)
    later_id = _audit_request(
        1,
        session_id=session.id,
        turn_index=1,
        created_at=shared_time,
        request_id="req-b",
    )
    earlier_id = _audit_request(
        2,
        session_id=session.id,
        turn_index=1,
        created_at=shared_time,
        request_id="req-a",
    )
    empty_messages = replace(
        _audit_request(
            3,
            session_id=session.id,
            turn_index=2,
            created_at=BASE + timedelta(seconds=10),
            request_id="req-c",
        ),
        request_messages=[],
        message_hashes=[],
    )
    for request in (root, later_id, earlier_id, empty_messages):
        await repository.record_turn(session=session, request=request, diff=None)

    summaries = await repository.list_session_request_summaries(session_id=session.id)

    assert [summary.request_id for summary in summaries] == [
        "root-0",
        "req-a",
        "req-b",
        "req-c",
    ]
    assert [summary.request_message_count for summary in summaries] == [1, 1, 1, 0]
    assert summaries[0].created_at == root.created_at
    assert summaries[0].parent_request_id is None
    assert summaries[0].status == root.status
    assert not hasattr(summaries[0], "request_messages")
    assert not hasattr(summaries[0], "request_params")
    assert not hasattr(summaries[0], "response_content")
    assert await repository.list_session_request_summaries(session_id=uuid4()) == []
