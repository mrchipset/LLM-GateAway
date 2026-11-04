from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx

from llm_gateway.auth.keys import generate_api_key
from llm_gateway.auth.passwords import hash_password
from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.storage.repositories import (
    AdminRole,
    AdminUser,
    ApiKeyRecord,
    AuditRequestRecord,
    AuditSessionRecord,
    Tenant,
)
from support import FrozenClock, seed_tenant

BASE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
MODEL = "fake-model"
PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "x-csrf-token"


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
        name="audit export key",
        now=container.clock.now(),
    )
    await container.api_keys.create_key(record)
    return record


async def _seed_turn(
    container: Container,
    *,
    tenant_id: UUID,
    key: ApiKeyRecord,
    session_id: UUID,
    request_id: str,
    created_at: datetime,
    messages: list[dict[str, object]] | None = None,
    params: dict[str, object] | None = None,
    response_content: str | None = "reply",
) -> AuditRequestRecord:
    request_messages = messages if messages is not None else [{"role": "user", "content": "hi"}]
    request = AuditRequestRecord(
        request_id=request_id,
        session_id=session_id,
        parent_request_id=None,
        tenant_id=tenant_id,
        api_key_id=key.id,
        turn_index=1,
        match_method="new",
        change_type="new_session",
        model_id=MODEL,
        provider="fake",
        is_stream=False,
        request_messages=request_messages,
        message_hashes=[],
        request_params=params if params is not None else {"model": MODEL},
        response_content=response_content,
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
    session = AuditSessionRecord(
        id=session_id,
        tenant_id=tenant_id,
        external_session_id=None,
        api_key_id=key.id,
        api_key_prefix=key.key_prefix,
        root_request_id=request_id,
        model_id=MODEL,
        provider="fake",
        title_preview="export",
        created_at=created_at,
        last_seen_at=created_at,
        request_count=1,
        total_tokens=5,
    )
    await container.audit.record_turn(session=session, request=request, diff=None)
    return request


async def _make_admin(
    container: Container,
    *,
    username: str,
    role: AdminRole,
) -> AdminUser:
    now = container.clock.now()
    return await container.admins.create_admin(
        AdminUser(
            id=uuid4(),
            username=username,
            display_name=username.title(),
            role=role,
            password_hash=hash_password(PASSWORD),
            active=True,
            created_at=now,
            updated_at=now,
            password_changed_at=now,
        )
    )


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    token = client.cookies.get("gw_admin_csrf")
    assert token is not None
    return {CSRF_HEADER: token}


async def test_export_jsonl_streams_records_with_content(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container, name="tenant-export")
    key = await _key(container, tenant)
    first_session = uuid4()
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=first_session,
        request_id="req-export-1",
        created_at=BASE,
        messages=[{"role": "user", "content": "first secret"}],
        params={"model": MODEL, "temperature": 0.2},
        response_content="first reply",
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=uuid4(),
        request_id="req-export-2",
        created_at=BASE.replace(hour=1),
        messages=[{"role": "user", "content": "second secret"}],
        response_content="second reply",
    )

    async with make_client(settings, container) as client:
        response = await client.get(
            "/api/v1/audit/export",
            params={
                "tenant_id": str(tenant.id),
                "since": _iso(BASE),
                "until": _iso(BASE.replace(hour=2)),
                "format": "jsonl",
            },
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="audit-{tenant.id}-2026-01-01-2026-01-01.jsonl"'
    )
    lines = [line for line in response.text.splitlines() if line]
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    assert [row["request_id"] for row in rows] == ["req-export-1", "req-export-2"]
    first = rows[0]
    assert first["session_id"] == str(first_session)
    assert first["tenant_id"] == str(tenant.id)
    assert first["request_messages"] == [{"role": "user", "content": "first secret"}]
    assert first["request_params"] == {"model": MODEL, "temperature": 0.2}
    assert first["response_content"] == "first reply"
    assert first["created_at"].startswith("2026-01-01T00:00:00")


async def test_export_csv_has_header_and_parses_json_columns(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container, name="tenant-csv")
    key = await _key(container, tenant)
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=uuid4(),
        request_id="req-csv-1",
        created_at=BASE,
        messages=[{"role": "user", "content": "csv secret"}],
        params={"model": MODEL, "top_p": 0.5},
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=uuid4(),
        request_id="req-csv-2",
        created_at=BASE.replace(hour=1),
    )

    async with make_client(settings, container) as client:
        response = await client.get(
            "/api/v1/audit/export",
            params={
                "tenant_id": str(tenant.id),
                "since": _iso(BASE),
                "until": _iso(BASE.replace(hour=2)),
                "format": "csv",
            },
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    reader = csv.reader(io.StringIO(response.text))
    header = next(reader)
    assert header[0] == "request_id"
    assert "request_messages" in header
    assert "response_content" in header
    rows = list(reader)
    assert len(rows) == 2

    first = dict(zip(header, rows[0], strict=True))
    assert first["request_id"] == "req-csv-1"
    assert json.loads(first["request_messages"]) == [{"role": "user", "content": "csv secret"}]
    assert json.loads(first["request_params"]) == {"model": MODEL, "top_p": 0.5}
    assert first["response_content"] == "reply"


async def test_export_rejects_inverted_window_and_non_audit_role(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container, name="tenant-rbac")
    await _make_admin(container, username="operator", role=AdminRole.OPERATOR)
    window = {
        "tenant_id": str(tenant.id),
        "since": _iso(BASE),
        "until": _iso(BASE.replace(hour=2)),
    }

    async with make_client(settings, container) as client:
        inverted = await client.get(
            "/api/v1/audit/export",
            params={
                "tenant_id": str(tenant.id),
                "since": _iso(BASE.replace(hour=2)),
                "until": _iso(BASE),
            },
            headers=_auth(_master(settings)),
        )
        await _login(client, "operator")
        forbidden = await client.get(
            "/api/v1/audit/export",
            params=window,
        )

    assert inverted.status_code == 400
    assert _error(inverted)["code"] == "invalid_request_body"
    assert forbidden.status_code == 403
    assert _error(forbidden)["code"] == "admin_forbidden"


async def test_delete_dry_run_reports_count_without_writing(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container, name="tenant-dry-run")
    key = await _key(container, tenant)
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=uuid4(),
        request_id="req-old",
        created_at=BASE,
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=uuid4(),
        request_id="req-new",
        created_at=BASE.replace(hour=10),
    )
    cutoff = BASE.replace(hour=5)

    async with make_client(settings, container) as client:
        response = await client.delete(
            "/api/v1/audit",
            params={
                "tenant_id": str(tenant.id),
                "before": _iso(cutoff),
                "dry_run": "true",
            },
            headers=_auth(_master(settings)),
        )
        exported = await client.get(
            "/api/v1/audit/export",
            params={
                "tenant_id": str(tenant.id),
                "since": _iso(BASE),
                "until": _iso(cutoff),
            },
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["requests_deleted"] == 1
    assert body["sessions_deleted"] == 0
    assert body["requests_remaining"] == 1
    assert len([line for line in exported.text.splitlines() if line]) == 1


async def test_delete_removes_window_and_orphan_sessions(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container, name="tenant-delete")
    key = await _key(container, tenant)
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=uuid4(),
        request_id="req-old-a",
        created_at=BASE,
    )
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=uuid4(),
        request_id="req-old-b",
        created_at=BASE.replace(hour=1),
    )
    newer_session = uuid4()
    await _seed_turn(
        container,
        tenant_id=tenant.id,
        key=key,
        session_id=newer_session,
        request_id="req-new",
        created_at=BASE.replace(hour=10),
    )
    cutoff = BASE.replace(hour=5)

    async with make_client(settings, container) as client:
        response = await client.delete(
            "/api/v1/audit",
            params={
                "tenant_id": str(tenant.id),
                "before": _iso(cutoff),
                "batch_size": 1,
            },
            headers=_auth(_master(settings)),
        )
        removed_window = await client.get(
            "/api/v1/audit/export",
            params={
                "tenant_id": str(tenant.id),
                "since": _iso(BASE),
                "until": _iso(cutoff),
            },
            headers=_auth(_master(settings)),
        )
        remaining_sessions = await client.get(
            "/api/v1/audit/sessions",
            params={"tenant_id": str(tenant.id), "since": _iso(BASE)},
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["requests_deleted"] == 2
    assert body["sessions_deleted"] == 2
    assert body["requests_remaining"] == 0
    assert [line for line in removed_window.text.splitlines() if line] == []
    assert [item["id"] for item in remaining_sessions.json()["items"]] == [str(newer_session)]


async def test_delete_max_batches_reports_remaining_requests(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container, name="tenant-truncated")
    key = await _key(container, tenant)
    for index in range(3):
        await _seed_turn(
            container,
            tenant_id=tenant.id,
            key=key,
            session_id=uuid4(),
            request_id=f"req-old-{index}",
            created_at=BASE.replace(hour=index),
        )
    cutoff = BASE.replace(hour=5)

    async with make_client(settings, container) as client:
        response = await client.delete(
            "/api/v1/audit",
            params={
                "tenant_id": str(tenant.id),
                "before": _iso(cutoff),
                "batch_size": 1,
                "max_batches": 1,
            },
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["requests_deleted"] == 1
    assert body["requests_remaining"] == 2


async def test_delete_requires_owner(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    tenant = await seed_tenant(container, name="tenant-delete-rbac")
    await _make_admin(container, username="operator", role=AdminRole.OPERATOR)
    await _make_admin(container, username="auditor", role=AdminRole.AUDITOR)
    params = {
        "tenant_id": str(tenant.id),
        "before": _iso(BASE),
        "dry_run": "true",
    }

    async with make_client(settings, container) as client:
        operator_csrf = await _login(client, "operator")
        operator = await client.delete(
            "/api/v1/audit",
            params=params,
            headers=operator_csrf,
        )
        auditor_csrf = await _login(client, "auditor")
        auditor = await client.delete(
            "/api/v1/audit",
            params=params,
            headers=auditor_csrf,
        )

    assert operator.status_code == 403
    assert _error(operator)["code"] == "admin_forbidden"
    assert auditor.status_code == 403
    assert _error(auditor)["code"] == "admin_forbidden"
