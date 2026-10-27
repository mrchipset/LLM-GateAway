from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from llm_gateway.auth.keys import generate_api_key
from llm_gateway.config import Environment, Settings
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.chat import ChatCompletionRequest, Usage
from llm_gateway.services.audit import (
    AUDIT_SESSION_HEADER,
    AuditService,
    AuditTurn,
    record_audit_safely,
)
from llm_gateway.services.audit_diff import text_hash
from llm_gateway.storage.memory import InMemoryTenantRepository
from llm_gateway.storage.repositories import (
    ApiKeyRecord,
    AuditRequestRecord,
    AuditSessionRecord,
    AuditTurnDiffRecord,
    Tenant,
)
from support import (
    CapturingAuditRepository,
    FailingAuditRepository,
    FrozenClock,
)

MASTER_KEY = "test-master-key-0123456789abcdef"
MODEL = "fake-model"
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _settings(
    *,
    audit_enabled: bool = True,
    audit_max_content_bytes: int = 262144,
) -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": MASTER_KEY,
            "audit_enabled": audit_enabled,
            "audit_max_content_bytes": audit_max_content_bytes,
        }
    )


def _payload(*messages: dict[str, Any], **kwargs: Any) -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(
        {"model": MODEL, "messages": list(messages), **kwargs}
    )


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def _assistant(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": text}


def _system(text: str) -> dict[str, Any]:
    return {"role": "system", "content": text}


async def _tenant(
    repository: InMemoryTenantRepository,
    *,
    audit_enabled: bool = True,
    name: str = "tenant",
    tenant_id: UUID | None = None,
) -> Tenant:
    tenant = Tenant(
        id=tenant_id or uuid4(),
        name=name,
        created_at=NOW,
        audit_enabled=audit_enabled,
    )
    return await repository.create_tenant(tenant)


def _key(tenant: Tenant) -> ApiKeyRecord:
    _secret, record = generate_api_key(
        key_id=uuid4(),
        tenant_id=tenant.id,
        name="audit key",
        now=NOW,
    )
    return record


def _service(
    settings: Settings,
    *,
    repository: Any,
    tenants: InMemoryTenantRepository,
) -> AuditService:
    return AuditService(
        settings=settings,
        repository=repository,
        tenants=tenants,
        clock=FrozenClock(),
    )


async def _begin(
    service: AuditService,
    tenant: Tenant,
    key: ApiKeyRecord,
    payload: ChatCompletionRequest,
    *,
    request_id: str,
    header: str | None = None,
    is_stream: bool = False,
) -> AuditTurn | None:
    return await service.begin(
        tenant_id=tenant.id,
        api_key=key,
        request_id=request_id,
        model_id=payload.model,
        payload=payload,
        session_header=header,
        is_stream=is_stream,
    )


async def _finish(
    service: AuditService,
    turn: AuditTurn,
    *,
    content: str = "reply",
    status: str = "completed",
) -> None:
    await service.finish(
        turn=turn,
        provider="fake",
        status=status,
        response_content=content,
        response_tool_calls=None,
        finish_reason="stop",
        usage=Usage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
    )


def _snapshot_bytes(messages: list[dict[str, Any]], response: str | None) -> int:
    payload = {"messages": messages, "response": response}
    return len(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


class ExplodingTenantRepository(InMemoryTenantRepository):
    async def get_tenant(self, tenant_id: UUID) -> Tenant | None:
        raise AssertionError("tenant must not be read when global audit is disabled")


class WriteFailingAuditRepository(CapturingAuditRepository):
    async def record_turn(
        self,
        *,
        session: AuditSessionRecord,
        request: AuditRequestRecord,
        diff: AuditTurnDiffRecord | None,
    ) -> None:
        raise RuntimeError("audit storage unavailable")


async def test_global_flag_off_returns_none_without_reading_or_writing() -> None:
    repository = FailingAuditRepository()
    service = _service(
        _settings(audit_enabled=False),
        repository=repository,
        tenants=ExplodingTenantRepository(),
    )

    turn = await service.begin(
        tenant_id=uuid4(),
        api_key=ApiKeyRecord(
            id=uuid4(),
            tenant_id=uuid4(),
            name="k",
            key_hash="a" * 64,
            key_prefix="sk-gw",
            created_at=NOW,
        ),
        request_id="req-off",
        model_id=MODEL,
        payload=_payload(_user("hello")),
        session_header="sess-1",
        is_stream=False,
    )

    assert turn is None


async def test_tenant_flag_off_returns_none_and_writes_nothing() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants, audit_enabled=False)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)

    turn = await _begin(
        service,
        tenant,
        _key(tenant),
        _payload(_user("hello")),
        request_id="req-tenant-off",
        header="sess-1",
    )

    assert turn is None
    assert capture.record_turn_calls == 0


async def test_explicit_header_groups_turns_into_one_session_with_continuations() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)
    key = _key(tenant)

    history = [_user("hello")]
    payloads = [
        _payload(*history),
        _payload(*history, _assistant("hi"), _user("second")),
        _payload(
            *history,
            _assistant("hi"),
            _user("second"),
            _assistant("again"),
            _user("third"),
        ),
    ]
    for index, payload in enumerate(payloads):
        turn = await _begin(
            service,
            tenant,
            key,
            payload,
            request_id=f"req-{index}",
            header="sess-1",
        )
        assert turn is not None
        await _finish(service, turn, content=f"reply-{index}")

    assert capture.record_turn_calls == 3
    assert {record.session_id for record in capture.requests} == {capture.requests[0].session_id}
    assert [record.turn_index for record in capture.requests] == [1, 2, 3]
    assert [record.parent_request_id for record in capture.requests] == [
        None,
        "req-0",
        "req-1",
    ]
    assert [record.match_method for record in capture.requests] == [
        "explicit",
        "explicit",
        "explicit",
    ]
    assert [record.change_type for record in capture.requests] == [
        "new_session",
        "continuation",
        "continuation",
    ]
    assert [session.external_session_id for session in capture.sessions] == [
        "sess-1",
        "sess-1",
        "sess-1",
    ]

    stored = await capture.get_session(session_id=capture.requests[0].session_id)
    assert stored is not None
    assert stored.request_count == 3
    assert stored.total_tokens == 15


async def test_same_messages_classify_regeneration_edit_and_truncation() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)
    key = _key(tenant)

    payloads = [
        _payload(_user("a"), _assistant("b")),
        _payload(_user("a"), _assistant("b")),
        _payload(_user("a"), _assistant("c")),
        _payload(_user("a")),
    ]
    for index, payload in enumerate(payloads):
        turn = await _begin(
            service,
            tenant,
            key,
            payload,
            request_id=f"flow-{index}",
            header="flow",
        )
        assert turn is not None
        await _finish(service, turn)

    assert [record.change_type for record in capture.requests] == [
        "new_session",
        "regeneration",
        "edit",
        "truncation",
    ]


async def test_prefix_fallback_merges_shared_first_user_but_not_shared_system_only() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)
    key = _key(tenant)

    first = _payload(_system("rules"), _user("hello"))
    turn = await _begin(service, tenant, key, first, request_id="prefix-0")
    assert turn is not None
    await _finish(service, turn)

    continuation = _payload(
        _system("rules"),
        _user("hello"),
        _assistant("hi"),
        _user("next"),
    )
    turn = await _begin(service, tenant, key, continuation, request_id="prefix-1")
    assert turn is not None
    await _finish(service, turn)

    unrelated = _payload(_system("rules"), _user("different"))
    turn = await _begin(service, tenant, key, unrelated, request_id="prefix-2")
    assert turn is not None
    await _finish(service, turn)

    assert [record.match_method for record in capture.requests] == ["new", "prefix", "new"]
    assert capture.requests[1].session_id == capture.requests[0].session_id
    assert capture.requests[1].turn_index == 2
    assert capture.requests[1].parent_request_id == "prefix-0"
    assert capture.requests[2].session_id != capture.requests[0].session_id
    assert capture.requests[2].turn_index == 1


async def test_same_external_session_id_in_two_tenants_stays_isolated() -> None:
    tenants = InMemoryTenantRepository()
    first_tenant = await _tenant(tenants, name="first")
    second_tenant = await _tenant(tenants, name="second")
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)

    first_turn = await _begin(
        service,
        first_tenant,
        _key(first_tenant),
        _payload(_user("hello")),
        request_id="tenant-a",
        header="shared",
    )
    second_turn = await _begin(
        service,
        second_tenant,
        _key(second_tenant),
        _payload(_user("hello")),
        request_id="tenant-b",
        header="shared",
    )
    assert first_turn is not None
    assert second_turn is not None
    await _finish(service, first_turn)
    await _finish(service, second_turn)

    first_stored = await capture.get_session_by_external_id(
        tenant_id=first_tenant.id, external_session_id="shared"
    )
    second_stored = await capture.get_session_by_external_id(
        tenant_id=second_tenant.id, external_session_id="shared"
    )
    assert first_stored is not None
    assert second_stored is not None
    assert first_stored.id != second_stored.id
    assert capture.record_turn_calls == 2


async def test_invalid_session_header_raises_client_error_without_writing() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)

    with pytest.raises(ApiError) as raised:
        await _begin(
            service,
            tenant,
            _key(tenant),
            _payload(_user("hello")),
            request_id="bad-header",
            header="not a valid header",
        )

    error = raised.value
    assert error.status_code == 400
    assert error.code is ApiErrorCode.INVALID_SESSION_ID
    assert error.param == AUDIT_SESSION_HEADER
    assert capture.record_turn_calls == 0


async def test_truncation_bounds_stored_snapshot_and_marks_it() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(
        _settings(audit_max_content_bytes=1024),
        repository=capture,
        tenants=tenants,
    )

    turn = await _begin(
        service,
        tenant,
        _key(tenant),
        _payload(_user("x" * 5000)),
        request_id="truncated",
        header="truncate",
    )
    assert turn is not None
    await _finish(service, turn, content="y" * 5000)

    stored = capture.requests[0]
    assert stored.truncated is True
    assert _snapshot_bytes(stored.request_messages, stored.response_content) <= 1024
    assert stored.response_content_hash is not None


async def test_record_failure_is_swallowed_and_logs_without_content(caplog: Any) -> None:
    caplog.set_level(logging.WARNING, logger="llm_gateway.services.audit")
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = WriteFailingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)

    turn = await _begin(
        service,
        tenant,
        _key(tenant),
        _payload(_user("TOP_SECRET_PROMPT")),
        request_id="write-fails",
        header="failing",
    )
    assert turn is not None

    await record_audit_safely(
        service=service,
        turn=turn,
        provider="fake",
        status="completed",
        response_content="TOP_SECRET_RESPONSE",
        response_tool_calls=None,
        finish_reason="stop",
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    records = [
        record
        for record in caplog.records
        if record.name == "llm_gateway.services.audit"
        and record.getMessage() == "audit_record_failed"
    ]
    assert len(records) == 1
    assert records[0].__dict__["error"] == "RuntimeError"
    assert "TOP_SECRET_PROMPT" not in caplog.text
    assert "TOP_SECRET_RESPONSE" not in caplog.text
    for record in caplog.records:
        assert "TOP_SECRET_PROMPT" not in str(record.__dict__)
        assert "TOP_SECRET_RESPONSE" not in str(record.__dict__)


async def test_prefix_fallback_does_not_merge_different_api_keys_of_one_tenant() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)
    first_key = _key(tenant)
    second_key = _key(tenant)

    first = _payload(_system("same rules"), _user("same opening"))
    turn = await _begin(service, tenant, first_key, first, request_id="key-a-0")
    assert turn is not None
    await _finish(service, turn)

    continuation = _payload(
        _system("same rules"),
        _user("same opening"),
        _assistant("hi"),
        _user("next"),
    )
    turn = await _begin(service, tenant, second_key, continuation, request_id="key-b-0")
    assert turn is not None
    await _finish(service, turn)

    assert [record.match_method for record in capture.requests] == ["new", "new"]
    assert capture.requests[0].session_id != capture.requests[1].session_id
    assert capture.requests[1].turn_index == 1
    assert capture.requests[1].parent_request_id is None
    assert capture.requests[1].api_key_id == second_key.id


async def test_explicit_header_spans_different_api_keys_within_a_tenant() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)
    first_key = _key(tenant)
    second_key = _key(tenant)

    first = _payload(_user("hello"))
    turn = await _begin(
        service, tenant, first_key, first, request_id="span-0", header="span-session"
    )
    assert turn is not None
    await _finish(service, turn)

    second = _payload(_user("hello"), _assistant("hi"), _user("next"))
    turn = await _begin(
        service, tenant, second_key, second, request_id="span-1", header="span-session"
    )
    assert turn is not None
    await _finish(service, turn)

    assert [record.match_method for record in capture.requests] == ["explicit", "explicit"]
    assert capture.requests[0].session_id == capture.requests[1].session_id
    assert [record.turn_index for record in capture.requests] == [1, 2]
    assert capture.requests[1].parent_request_id == "span-0"
    assert capture.requests[1].api_key_id == second_key.id


async def test_precreated_explicit_session_has_one_request_after_first_turn() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)

    turn = await _begin(
        service,
        tenant,
        _key(tenant),
        _payload(_user("hello")),
        request_id="solo-0",
        header="solo-session",
    )
    assert turn is not None
    await _finish(service, turn)

    stored = await capture.get_session(session_id=turn.session_id)
    assert stored is not None
    assert stored.request_count == 1
    assert stored.total_tokens == 5
    assert stored.provider == "fake"
    assert stored.external_session_id == "solo-session"


async def test_finish_truncates_params_and_tool_calls_but_diffs_original_values() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(
        _settings(audit_max_content_bytes=1024),
        repository=capture,
        tenants=tenants,
    )
    key = _key(tenant)

    parent = _payload(_user("hello"))
    turn = await _begin(service, tenant, key, parent, request_id="budget-0", header="budget")
    assert turn is not None
    await _finish(service, turn, content="ok")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "d" * 2000,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "q": {
                            "type": "string",
                            "description": "q" * 2000,
                        }
                    },
                },
            },
        }
    ]
    response_calls = [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "lookup", "arguments": "a" * 5000},
        }
    ]
    response_content = "r" * 200
    payload = _payload(
        _user("hello"),
        _assistant("ok"),
        _user("next"),
        tools=tools,
    )
    turn = await _begin(service, tenant, key, payload, request_id="budget-1", header="budget")
    assert turn is not None
    await service.finish(
        turn=turn,
        provider="fake",
        status="completed",
        response_content=response_content,
        response_tool_calls=response_calls,
        finish_reason="tool_calls",
        usage=Usage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
    )

    record = capture.requests[-1]
    assert record.truncated is True
    assert record.response_content_hash == text_hash(response_content)

    stored_tools = record.request_params["tools"]
    assert isinstance(stored_tools, list)
    stored_function = stored_tools[0]["function"]
    assert isinstance(stored_function, dict)
    assert stored_function["description"] != "d" * 2000
    assert len(str(stored_function["description"])) < 2000

    assert record.response_tool_calls is not None
    stored_call_function = record.response_tool_calls[0]["function"]
    assert isinstance(stored_call_function, dict)
    assert stored_call_function["arguments"] != "a" * 5000
    assert len(str(stored_call_function["arguments"])) < 5000

    diff = capture.diffs[-1]
    assert diff is not None
    canonical_tools = json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert diff.parameter_changes["tools"] == {
        "from_hash": None,
        "to_hash": hashlib.sha256(canonical_tools.encode("utf-8")).hexdigest(),
        "truncated": True,
    }
    assert "d" * 2000 not in json.dumps(diff.parameter_changes)


async def test_finish_keeps_small_parameter_changes_as_from_to() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)
    key = _key(tenant)

    first = _payload(_user("hello"), temperature=0.1)
    turn = await _begin(
        service, tenant, key, first, request_id="small-params-0", header="small-params"
    )
    assert turn is not None
    await _finish(service, turn)

    second = _payload(_user("hello"), temperature=0.7)
    turn = await _begin(
        service, tenant, key, second, request_id="small-params-1", header="small-params"
    )
    assert turn is not None
    await _finish(service, turn)

    diff = capture.diffs[-1]
    assert diff is not None
    assert diff.parameter_changes["temperature"] == {"from": 0.1, "to": 0.7}


async def test_finish_keeps_none_response_tool_calls_as_none() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)

    turn = await _begin(
        service,
        tenant,
        _key(tenant),
        _payload(_user("hello")),
        request_id="no-tools",
        header="no-tools",
    )
    assert turn is not None
    await _finish(service, turn)

    assert capture.requests[0].response_tool_calls is None
    assert capture.requests[0].truncated is False
