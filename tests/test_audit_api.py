from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx

from llm_gateway.auth.keys import generate_api_key
from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.schemas.chat import ChatCompletionRequest, Usage
from llm_gateway.services.audit import AuditService
from llm_gateway.services.audit_diff import (
    bound_parameter_changes,
    message_hashes,
    truncate_snapshot,
)
from llm_gateway.storage.repositories import (
    ApiKeyRecord,
    AuditMatchMethod,
    AuditRequestRecord,
    AuditSessionRecord,
    AuditTurnDiffRecord,
    Tenant,
)
from support import FrozenClock, seed_api_key, seed_model, seed_tenant

BASE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
MODEL = "fake-model"


def _master(settings: Settings) -> str:
    return settings.master_key.get_secret_value()


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _error(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    error = body["error"]
    assert isinstance(error, dict)
    return error


def _iso(value: datetime) -> str:
    return value.isoformat()


async def _key(container: Container, tenant: Tenant) -> ApiKeyRecord:
    _secret, record = generate_api_key(
        key_id=uuid4(),
        tenant_id=tenant.id,
        name="audit key",
        now=container.clock.now(),
    )
    await container.api_keys.create_key(record)
    return record


def _diff(
    request_id: str,
    *,
    created_at: datetime,
    change_type: str = "new_session",
    previous_request_id: str | None = None,
    added_messages: list[dict[str, object]] | None = None,
    modified_messages: list[dict[str, object]] | None = None,
    removed_messages: list[dict[str, object]] | None = None,
    parameter_changes: dict[str, dict[str, object]] | None = None,
) -> AuditTurnDiffRecord:
    return AuditTurnDiffRecord(
        request_id=request_id,
        previous_request_id=previous_request_id,
        change_type=change_type,
        common_prefix=0,
        added_messages=added_messages or [],
        modified_messages=modified_messages or [],
        removed_messages=removed_messages or [],
        parameter_changes=parameter_changes or {},
        usage_delta={
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "cached_tokens": 0,
            "total_tokens": 3,
        },
        response_change={
            "content_changed": False,
            "previous_content_hash": None,
            "content_hash": None,
            "finish_reason_changed": False,
            "previous_finish_reason": None,
            "finish_reason": None,
            "tool_calls_added": 0,
            "tool_calls_removed": 0,
            "tool_call_names": [],
        },
        created_at=created_at,
    )


async def _seed_turn(
    container: Container,
    *,
    tenant_id: UUID,
    key: ApiKeyRecord,
    session_id: UUID,
    request_id: str,
    created_at: datetime,
    turn_index: int = 1,
    parent_request_id: str | None = None,
    change_type: str = "new_session",
    match_method: AuditMatchMethod = "new",
    title_preview: str = "hello world",
    model_id: str = MODEL,
    messages: list[dict[str, object]] | None = None,
    params: dict[str, object] | None = None,
    response_content: str | None = "reply",
    response_tool_calls: list[dict[str, object]] | None = None,
    truncated: bool = False,
    diff: AuditTurnDiffRecord | None = None,
    total_tokens: int | None = 5,
    status: str = "completed",
    is_stream: bool = False,
    root_request_id: str | None = None,
) -> AuditRequestRecord:
    request_messages = messages if messages is not None else [{"role": "user", "content": "hi"}]
    request_params = params if params is not None else {"model": model_id}
    request = AuditRequestRecord(
        request_id=request_id,
        session_id=session_id,
        parent_request_id=parent_request_id,
        tenant_id=tenant_id,
        api_key_id=key.id,
        turn_index=turn_index,
        match_method=match_method,
        change_type=change_type,
        model_id=model_id,
        provider="fake",
        is_stream=is_stream,
        request_messages=request_messages,
        message_hashes=message_hashes(request_messages),
        request_params=request_params,
        response_content=response_content,
        response_tool_calls=response_tool_calls,
        response_content_hash=None,
        finish_reason="stop",
        status=status,
        prompt_tokens=3 if total_tokens is not None else None,
        completion_tokens=2 if total_tokens is not None else None,
        cached_tokens=0 if total_tokens is not None else None,
        total_tokens=total_tokens,
        truncated=truncated,
        created_at=created_at,
    )
    session = AuditSessionRecord(
        id=session_id,
        tenant_id=tenant_id,
        external_session_id=None,
        api_key_id=key.id,
        api_key_prefix=key.key_prefix,
        root_request_id=root_request_id if root_request_id is not None else request_id,
        model_id=model_id,
        provider="fake",
        title_preview=title_preview,
        created_at=created_at,
        last_seen_at=created_at,
        request_count=1,
        total_tokens=total_tokens or 0,
    )
    await container.audit.record_turn(session=session, request=request, diff=diff)
    return request


async def test_audit_routes_require_master_key(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    inference_key = await seed_api_key(container)

    async with make_client(settings, container) as client:
        missing = await client.get("/api/v1/audit/sessions")
        inference = await client.get("/api/v1/audit/sessions", headers=_auth(inference_key))
        master = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE)},
            headers=_auth(_master(settings)),
        )

    assert missing.status_code == 401
    assert _error(missing)["code"] == "master_key_required"
    assert missing.headers["x-request-id"] == _error(missing)["request_id"]
    assert inference.status_code == 401
    assert _error(inference)["code"] == "invalid_api_key"
    assert master.status_code == 200


async def test_list_sessions_empty_page_shape(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())

    async with make_client(settings, container) as client:
        response = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE)},
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_list_sessions_filters_by_tenant_key_and_model(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    await seed_model(container, model_id="model-a")
    await seed_model(container, model_id="model-b")
    tenant_a = await seed_tenant(container, name="tenant-a")
    tenant_b = await seed_tenant(container, name="tenant-b")
    key_a1 = await _key(container, tenant_a)
    key_a2 = await _key(container, tenant_a)
    key_b1 = await _key(container, tenant_b)
    session_a1 = uuid4()
    session_a2 = uuid4()
    session_b1 = uuid4()
    await _seed_turn(
        container,
        tenant_id=tenant_a.id,
        key=key_a1,
        session_id=session_a1,
        request_id="req-a1",
        created_at=BASE,
        model_id="model-a",
    )
    await _seed_turn(
        container,
        tenant_id=tenant_a.id,
        key=key_a2,
        session_id=session_a2,
        request_id="req-a2",
        created_at=BASE,
        model_id="model-b",
    )
    await _seed_turn(
        container,
        tenant_id=tenant_b.id,
        key=key_b1,
        session_id=session_b1,
        request_id="req-b1",
        created_at=BASE,
        model_id="model-a",
    )

    async with make_client(settings, container) as client:
        headers = _auth(_master(settings))
        by_tenant = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE), "tenant_id": str(tenant_a.id)},
            headers=headers,
        )
        by_key = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE), "api_key_id": str(key_a2.id)},
            headers=headers,
        )
        by_model = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE), "model_id": "model-a"},
            headers=headers,
        )

    assert by_tenant.status_code == 200
    assert {item["id"] for item in by_tenant.json()["items"]} == {
        str(session_a1),
        str(session_a2),
    }
    assert by_tenant.json()["total"] == 2
    assert [item["id"] for item in by_key.json()["items"]] == [str(session_a2)]
    assert {item["id"] for item in by_model.json()["items"]} == {
        str(session_a1),
        str(session_b1),
    }


async def test_list_sessions_uses_half_open_window(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    first = BASE.replace(hour=1)
    second = BASE.replace(hour=2)
    first_id = uuid4()
    second_id = uuid4()
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=first_id,
        request_id="req-first",
        created_at=first,
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=second_id,
        request_id="req-second",
        created_at=second,
    )

    async with make_client(settings, container) as client:
        headers = _auth(_master(settings))
        response = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(first), "until": _iso(second)},
            headers=headers,
        )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(first_id)]


async def test_list_sessions_q_matches_title_and_non_root_request_id(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    titled_id = uuid4()
    branched_id = uuid4()
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=titled_id,
        request_id="root-titled",
        created_at=BASE,
        title_preview="Quarterly Conversation",
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=branched_id,
        request_id="root-branch",
        created_at=BASE,
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=branched_id,
        request_id="followup-branch",
        created_at=BASE.replace(hour=1),
        turn_index=2,
        parent_request_id="root-branch",
        change_type="continuation",
        match_method="prefix",
    )

    async with make_client(settings, container) as client:
        headers = _auth(_master(settings))
        by_title = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE), "q": "conversation"},
            headers=headers,
        )
        by_branch_request = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE), "q": "followup"},
            headers=headers,
        )

    assert [item["id"] for item in by_title.json()["items"]] == [str(titled_id)]
    assert [item["id"] for item in by_branch_request.json()["items"]] == [str(branched_id)]


async def test_list_sessions_paginates_without_changing_total(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    session_ids = [uuid4() for _ in range(3)]
    for index, session_id in enumerate(session_ids):
        await _seed_turn(
            container,
            tenant_id=tenant.id,
            key=key,
            session_id=session_id,
            request_id=f"req-{index}",
            created_at=BASE.replace(hour=index),
        )

    async with make_client(settings, container) as client:
        headers = _auth(_master(settings))
        first = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE), "limit": 2, "offset": 0},
            headers=headers,
        )
        second = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE), "limit": 2, "offset": 2},
            headers=headers,
        )

    assert first.json()["total"] == 3
    assert len(first.json()["items"]) == 2
    assert first.json()["limit"] == 2
    assert second.json()["total"] == 3
    assert len(second.json()["items"]) == 1
    assert second.json()["offset"] == 2


async def test_list_sessions_orders_by_newest_last_seen(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    oldest = uuid4()
    middle = uuid4()
    newest = uuid4()
    for index, (session_id, label) in enumerate(
        [(oldest, "old"), (middle, "mid"), (newest, "new")]
    ):
        await _seed_turn(
            container,
            tenant_id=tenant.id,
            key=key,
            session_id=session_id,
            request_id=f"req-{label}",
            created_at=BASE.replace(hour=index),
        )

    async with make_client(settings, container) as client:
        response = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE)},
            headers=_auth(_master(settings)),
        )

    assert [item["id"] for item in response.json()["items"]] == [
        str(newest),
        str(middle),
        str(oldest),
    ]


async def test_list_sessions_rejects_unknown_tenant_naive_and_inverted_window(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())

    async with make_client(settings, container) as client:
        headers = _auth(_master(settings))
        unknown_tenant = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE), "tenant_id": str(uuid4())},
            headers=headers,
        )
        naive = await client.get(
            "/api/v1/audit/sessions",
            params={"since": "2026-01-01T00:00:00"},
            headers=headers,
        )
        inverted = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE), "until": _iso(BASE)},
            headers=headers,
        )
        missing_since = await client.get("/api/v1/audit/sessions", headers=headers)

    assert unknown_tenant.status_code == 404
    assert _error(unknown_tenant)["code"] == "tenant_not_found"
    assert naive.status_code == 400
    assert _error(naive)["code"] == "invalid_request_body"
    assert inverted.status_code == 400
    assert _error(inverted)["code"] == "invalid_request_body"
    assert missing_since.status_code == 400
    assert _error(missing_since)["code"] == "invalid_request_body"


async def test_session_detail_unknown_and_invalid_id(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())

    async with make_client(settings, container) as client:
        headers = _auth(_master(settings))
        unknown = await client.get(f"/api/v1/audit/sessions/{uuid4()}", headers=headers)
        invalid = await client.get("/api/v1/audit/sessions/not-a-uuid", headers=headers)

    assert unknown.status_code == 404
    assert _error(unknown)["code"] == "audit_session_not_found"
    assert invalid.status_code == 400
    assert _error(invalid)["code"] == "invalid_request_body"


async def test_session_detail_without_content_hides_content_but_keeps_diff(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    session_id = uuid4()
    diff = _diff(
        "req-session",
        created_at=BASE,
        added_messages=[{"index": 0, "role": "user", "hash": "h", "preview": "hi"}],
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=session_id,
        request_id="req-session",
        created_at=BASE,
        messages=[{"role": "user", "content": "secret prompt"}],
        params={"model": MODEL, "temperature": 0.2},
        response_content="secret response",
        response_tool_calls=[{"id": "call-1", "type": "function"}],
        diff=diff,
    )

    async with make_client(settings, container) as client:
        response = await client.get(
            f"/api/v1/audit/sessions/{session_id}", headers=_auth(_master(settings))
        )

    assert response.status_code == 200
    body = response.json()
    assert "truncated" not in body
    assert body["session"]["id"] == str(session_id)
    turn = body["turns"][0]
    assert turn["request_messages"] is None
    assert turn["request_params"] is None
    assert turn["response_content"] is None
    assert turn["response_tool_calls"] is None
    assert "secret" not in response.text
    assert turn["request_message_count"] == 1
    assert turn["diff"]["change_type"] == "new_session"
    assert turn["match_method"] == "new"


async def test_session_detail_with_content_returns_payloads(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    session_id = uuid4()
    tool_calls: list[dict[str, object]] = [
        {"id": "call-1", "type": "function", "function": {"name": "lookup"}}
    ]
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=session_id,
        request_id="req-content",
        created_at=BASE,
        messages=[{"role": "user", "content": "hello"}],
        params={"model": MODEL, "temperature": 0.2},
        response_content="world",
        response_tool_calls=tool_calls,
    )

    async with make_client(settings, container) as client:
        response = await client.get(
            f"/api/v1/audit/sessions/{session_id}",
            params={"include_content": "true"},
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    turn = response.json()["turns"][0]
    assert turn["request_messages"] == [{"role": "user", "content": "hello"}]
    assert turn["request_params"] == {"model": MODEL, "temperature": 0.2}
    assert turn["response_content"] == "world"
    assert turn["response_tool_calls"] == tool_calls


async def test_session_detail_content_budget_returns_413(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    tiny = settings.model_copy(update={"audit_max_content_bytes": 1024})
    container = make_container(tiny, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    session_id = uuid4()
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=session_id,
        request_id="req-huge",
        created_at=BASE,
        messages=[{"role": "user", "content": "x" * 4000}],
    )

    async with make_client(tiny, container) as client:
        headers = _auth(_master(tiny))
        without_content = await client.get(f"/api/v1/audit/sessions/{session_id}", headers=headers)
        with_content = await client.get(
            f"/api/v1/audit/sessions/{session_id}",
            params={"include_content": "true"},
            headers=headers,
        )

    assert without_content.status_code == 200
    without_turn = without_content.json()["turns"][0]
    assert without_turn["request_message_count"] == 1
    assert without_turn["request_messages"] is None
    assert without_turn["request_params"] is None
    assert without_turn["response_content"] is None
    assert with_content.status_code == 413
    assert _error(with_content)["code"] == "audit_content_too_large"


async def test_request_detail_returns_content_truncated_flag_and_diff(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    session_id = uuid4()
    tool_calls: list[dict[str, object]] = [{"id": "call-1", "type": "function"}]
    diff = _diff(
        "req-detail",
        created_at=BASE,
        change_type="edit",
        previous_request_id="req-parent",
        added_messages=[{"index": 1, "role": "user", "hash": "h1", "preview": "next"}],
        modified_messages=[
            {
                "index": 0,
                "role": "user",
                "before_hash": "a",
                "after_hash": "b",
                "before_preview": "old",
                "after_preview": "new",
            }
        ],
        removed_messages=[{"index": 2, "role": "assistant", "hash": "h2", "preview": "old"}],
        parameter_changes={
            "temperature": {"from": 0.1, "to": 0.2},
            "tools": {"from_hash": "f" * 64, "to_hash": "e" * 64, "truncated": True},
        },
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=session_id,
        request_id="req-detail",
        created_at=BASE,
        messages=[{"role": "user", "content": "hello"}],
        params={"model": MODEL},
        response_content="world",
        response_tool_calls=tool_calls,
        truncated=True,
        diff=diff,
    )

    async with make_client(settings, container) as client:
        response = await client.get(
            "/api/v1/audit/requests/req-detail", headers=_auth(_master(settings))
        )

    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    request = body["request"]
    assert request["request_id"] == "req-detail"
    assert request["request_messages"] == [{"role": "user", "content": "hello"}]
    assert request["request_params"] == {"model": MODEL}
    assert request["response_content"] == "world"
    assert request["response_tool_calls"] == tool_calls
    assert request["truncated"] is True
    assert body["diff"]["change_type"] == "edit"
    assert body["diff"]["added_messages"] == [
        {"index": 1, "role": "user", "hash": "h1", "preview": "next"}
    ]
    assert body["diff"]["modified_messages"] == [
        {
            "index": 0,
            "role": "user",
            "before_hash": "a",
            "after_hash": "b",
            "before_preview": "old",
            "after_preview": "new",
        }
    ]
    assert body["diff"]["removed_messages"] == [
        {"index": 2, "role": "assistant", "hash": "h2", "preview": "old"}
    ]
    assert body["diff"]["parameter_changes"]["temperature"] == {"from": 0.1, "to": 0.2}
    assert body["diff"]["parameter_changes"]["tools"] == {
        "from_hash": "f" * 64,
        "to_hash": "e" * 64,
        "truncated": True,
    }


async def test_request_detail_unknown_and_content_budget(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    tiny = settings.model_copy(update={"audit_max_content_bytes": 1024})
    container = make_container(tiny, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    session_id = uuid4()
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=session_id,
        request_id="req-oversized",
        created_at=BASE,
        messages=[{"role": "user", "content": "y" * 4000}],
    )

    async with make_client(tiny, container) as client:
        headers = _auth(_master(tiny))
        unknown = await client.get("/api/v1/audit/requests/missing", headers=headers)
        oversized = await client.get("/api/v1/audit/requests/req-oversized", headers=headers)

    assert unknown.status_code == 404
    assert _error(unknown)["code"] == "audit_request_not_found"
    assert oversized.status_code == 413
    assert _error(oversized)["code"] == "audit_content_too_large"


async def test_session_detail_without_content_returns_bounded_previews_and_hashed_parameters(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    service_settings = settings.model_copy(update={"audit_enabled": True})
    container = make_container(service_settings, clock=FrozenClock())
    tenant = await seed_tenant(container, audit_enabled=True)
    key = await _key(container, tenant)
    secret = "TOPSECRET-" + "A" * 400
    service = AuditService(
        settings=service_settings,
        repository=container.audit,
        tenants=container.tenants,
        clock=container.clock,
    )
    payload = ChatCompletionRequest.model_validate(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": secret}],
            "temperature": 0.7,
        }
    )
    turn = await service.begin(
        tenant_id=tenant.id,
        api_key=key,
        request_id="req-real-chain",
        model_id=MODEL,
        payload=payload,
        session_header=None,
        is_stream=False,
    )
    assert turn is not None
    await service.finish(
        turn=turn,
        provider="fake",
        status="completed",
        response_content="ok",
        response_tool_calls=None,
        finish_reason="stop",
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    async with make_client(service_settings, container) as client:
        response = await client.get(
            f"/api/v1/audit/sessions/{turn.session_id}",
            headers=_auth(_master(service_settings)),
        )

    assert response.status_code == 200
    body = response.json()
    assert secret not in response.text
    timeline = body["turns"][0]
    assert timeline["request_messages"] is None
    assert timeline["request_params"] is None
    assert timeline["response_content"] is None
    assert timeline["response_tool_calls"] is None
    added = timeline["diff"]["added_messages"]
    assert len(added) == 1
    assert added[0]["preview"] == secret[:160]
    parameter_changes = timeline["diff"]["parameter_changes"]
    assert set(parameter_changes) == {"model", "temperature"}
    for change in parameter_changes.values():
        assert set(change) == {"from_hash", "to_hash", "truncated"}
        assert change["truncated"] is True
    assert '"temperature":0.7' not in response.text


async def test_session_detail_include_content_reports_capture_truncation(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    session_id = uuid4()
    snapshot = truncate_snapshot(
        messages=[{"role": "user", "content": "z" * 4000}],
        response_content="r" * 4000,
        max_bytes=512,
    )
    assert snapshot.truncated is True
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=session_id,
        request_id="req-truncated",
        created_at=BASE,
        messages=snapshot.messages,
        response_content=snapshot.response_content,
        truncated=snapshot.truncated,
    )

    async with make_client(settings, container) as client:
        response = await client.get(
            f"/api/v1/audit/sessions/{session_id}",
            params={"include_content": "true"},
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    assert response.json()["turns"][0]["truncated"] is True


async def test_session_detail_budget_applies_without_content(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    tiny = settings.model_copy(update={"audit_max_content_bytes": 1024})
    container = make_container(tiny, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    session_id = uuid4()
    for index in range(8):
        await _seed_turn(
            container,
            tenant_id=tenant.id,
            key=key,
            session_id=session_id,
            request_id=f"req-preview-{index}",
            created_at=BASE.replace(minute=index),
            turn_index=index + 1,
            diff=_diff(
                f"req-preview-{index}",
                created_at=BASE.replace(minute=index),
                added_messages=[{"index": 0, "role": "user", "hash": "h", "preview": "p" * 160}],
            ),
        )

    async with make_client(tiny, container) as client:
        response = await client.get(
            f"/api/v1/audit/sessions/{session_id}",
            headers=_auth(_master(tiny)),
        )

    assert response.status_code == 413
    assert _error(response)["code"] == "audit_content_too_large"


async def test_list_sessions_rejects_oversized_q_and_limit(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())

    async with make_client(settings, container) as client:
        headers = _auth(_master(settings))
        long_query = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE), "q": "a" * 201},
            headers=headers,
        )
        huge_limit = await client.get(
            "/api/v1/audit/sessions",
            params={"since": _iso(BASE), "limit": 101},
            headers=headers,
        )

    assert long_query.status_code == 400
    assert _error(long_query)["code"] == "invalid_request_body"
    assert huge_limit.status_code == 400
    assert _error(huge_limit)["code"] == "invalid_request_body"


def _normalize_content_turn(turn: dict[str, Any]) -> dict[str, Any]:
    """Strip content and reduce parameter changes to the privacy-safe hash form."""

    normalized = copy.deepcopy(turn)
    for field in (
        "request_messages",
        "request_params",
        "response_content",
        "response_tool_calls",
    ):
        normalized[field] = None
    diff = normalized["diff"]
    if diff is not None:
        diff["parameter_changes"] = bound_parameter_changes(
            changes=diff["parameter_changes"],
            max_value_bytes=0,
        )
    return normalized


async def test_session_detail_content_modes_agree_on_metadata(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    session_id = uuid4()
    truncated_snapshot = truncate_snapshot(
        messages=[{"role": "user", "content": "z" * 4000}],
        response_content="r" * 4000,
        max_bytes=512,
    )
    assert truncated_snapshot.truncated is True

    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=session_id,
        request_id="req-root",
        created_at=BASE,
        messages=[{"role": "user", "content": "first"}],
        params={"model": MODEL},
        diff=_diff(
            "req-root",
            created_at=BASE,
            added_messages=[{"index": 0, "role": "user", "hash": "h0", "preview": "first"}],
            parameter_changes={"model": {"from": None, "to": MODEL}},
        ),
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=session_id,
        request_id="req-branch-a",
        created_at=BASE.replace(minute=1),
        turn_index=2,
        parent_request_id="req-root",
        change_type="continuation",
        match_method="prefix",
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "second"},
        ],
        params={"model": MODEL, "temperature": 0.2},
        diff=_diff(
            "req-branch-a",
            created_at=BASE.replace(minute=1),
            change_type="continuation",
            previous_request_id="req-root",
            added_messages=[{"index": 2, "role": "user", "hash": "h2", "preview": "second"}],
            parameter_changes={"temperature": {"from": None, "to": 0.2}},
        ),
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=session_id,
        request_id="req-branch-b",
        created_at=BASE.replace(minute=2),
        turn_index=2,
        parent_request_id="req-root",
        change_type="edit",
        match_method="prefix",
        messages=truncated_snapshot.messages,
        response_content=truncated_snapshot.response_content,
        truncated=truncated_snapshot.truncated,
        params={"model": MODEL, "top_p": 0.5},
        diff=_diff(
            "req-branch-b",
            created_at=BASE.replace(minute=2),
            change_type="edit",
            previous_request_id="req-root",
            modified_messages=[
                {
                    "index": 1,
                    "role": "user",
                    "before_hash": "before",
                    "after_hash": "after",
                    "before_preview": "before",
                    "after_preview": "after",
                }
            ],
            parameter_changes={"top_p": {"from": 0.9, "to": 0.5}},
        ),
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=session_id,
        request_id="req-tail",
        created_at=BASE.replace(minute=3),
        turn_index=3,
        parent_request_id="req-branch-a",
        change_type="continuation",
        match_method="prefix",
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "third"},
        ],
        params={"model": MODEL, "max_tokens": 200},
        diff=_diff(
            "req-tail",
            created_at=BASE.replace(minute=3),
            change_type="continuation",
            previous_request_id="req-branch-a",
            added_messages=[{"index": 4, "role": "user", "hash": "h4", "preview": "third"}],
            parameter_changes={"max_tokens": {"from": 100, "to": 200}},
        ),
    )

    async with make_client(settings, container) as client:
        headers = _auth(_master(settings))
        without_content = await client.get(f"/api/v1/audit/sessions/{session_id}", headers=headers)
        with_content = await client.get(
            f"/api/v1/audit/sessions/{session_id}",
            params={"include_content": "true"},
            headers=headers,
        )

    assert without_content.status_code == 200
    assert with_content.status_code == 200
    summary_turns = without_content.json()["turns"]
    content_turns = with_content.json()["turns"]
    assert [turn["turn_index"] for turn in summary_turns] == [1, 2, 2, 3]
    assert any(turn["truncated"] for turn in summary_turns)

    normalized_content = [_normalize_content_turn(turn) for turn in content_turns]
    assert summary_turns == normalized_content


async def test_session_detail_without_content_preserves_already_bounded_parameter_changes(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container)
    key = await _key(container, tenant)
    session_id = uuid4()
    plaintext_changes: dict[str, dict[str, object]] = {
        "tools": {
            "from": None,
            "to": [{"type": "function", "function": {"description": "d" * 500}}],
        },
        "temperature": {"from": 0.1, "to": 0.7},
    }
    bounded = bound_parameter_changes(changes=plaintext_changes, max_value_bytes=0)
    assert bounded["tools"]["truncated"] is True
    assert isinstance(bounded["tools"]["to_hash"], str)
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=session_id,
        request_id="req-bounded",
        created_at=BASE,
        diff=_diff("req-bounded", created_at=BASE, parameter_changes=bounded),
    )

    async with make_client(settings, container) as client:
        response = await client.get(
            f"/api/v1/audit/sessions/{session_id}",
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    parameter_changes = response.json()["turns"][0]["diff"]["parameter_changes"]
    assert parameter_changes == bounded
    assert parameter_changes["tools"]["to_hash"] == bounded["tools"]["to_hash"]
    for change in parameter_changes.values():
        assert "from" not in change
        assert "to" not in change
        assert change["truncated"] is True
    assert "d" * 500 not in response.text
