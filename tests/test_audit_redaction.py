from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from llm_gateway.auth.keys import generate_api_key
from llm_gateway.config import Environment, Settings
from llm_gateway.metrics import build_metrics, install_metrics, reset_metrics_for_tests
from llm_gateway.schemas.chat import ChatCompletionRequest, Usage
from llm_gateway.services.audit import AuditService, AuditTurn
from llm_gateway.storage.memory import InMemoryTenantRepository
from llm_gateway.storage.repositories import ApiKeyRecord, Tenant
from support import CapturingAuditRepository, FrozenClock

MASTER_KEY = "test-master-key-0123456789abcdef"
MODEL = "fake-model"
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
EMAIL = "alice@example.com"
SECOND_EMAIL = "bob@example.com"
REDACTED_EMAIL = "[redacted:email]"
REDACT_PATTERNS = json.dumps(
    [{"name": "email", "pattern": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"}]
)


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


def _counter_total(reader: InMemoryMetricReader, name: str, **labels: str) -> int:
    data = reader.get_metrics_data()
    if data is None:
        return 0
    points: list[Any] = []
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == name:
                    points.extend(metric.data.data_points)  # pyright: ignore[reportAttributeAccessIssue]
    total = 0
    for point in points:
        attributes = dict(point.attributes)
        if all(attributes.get(key) == value for key, value in labels.items()):
            total += int(point.value)
    return total


def _settings(*, patterns: str = REDACT_PATTERNS) -> Settings:
    return Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": MASTER_KEY,
            "audit_enabled": True,
            "audit_redact_patterns": patterns,
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


async def _tenant(repository: InMemoryTenantRepository) -> Tenant:
    tenant = Tenant(
        id=uuid4(),
        name="redaction-tenant",
        created_at=NOW,
        audit_enabled=True,
    )
    return await repository.create_tenant(tenant)


def _key(tenant: Tenant) -> ApiKeyRecord:
    _secret, record = generate_api_key(
        key_id=uuid4(),
        tenant_id=tenant.id,
        name="redaction key",
        now=NOW,
    )
    return record


def _service(
    settings: Settings,
    *,
    repository: CapturingAuditRepository,
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
) -> AuditTurn | None:
    return await service.begin(
        tenant_id=tenant.id,
        api_key=key,
        request_id=request_id,
        model_id=payload.model,
        payload=payload,
        session_header=header,
        is_stream=False,
    )


async def _finish(service: AuditService, turn: AuditTurn, *, content: str) -> None:
    await service.finish(
        turn=turn,
        provider="fake",
        status="completed",
        response_content=content,
        response_tool_calls=None,
        finish_reason="stop",
        usage=Usage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
    )


async def test_email_is_redacted_in_stored_messages_and_response() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)

    turn = await _begin(
        service,
        tenant,
        _key(tenant),
        _payload(_user(f"contact {EMAIL} now")),
        request_id="redact-message",
        header="redact-session",
    )
    assert turn is not None
    await _finish(service, turn, content=f"wrote to {EMAIL}")

    record = capture.requests[0]
    assert record.request_messages[0]["content"] == f"contact {REDACTED_EMAIL} now"
    assert record.response_content == f"wrote to {REDACTED_EMAIL}"
    assert EMAIL not in json.dumps(record.request_messages)
    assert EMAIL not in (record.response_content or "")


async def test_title_preview_is_redacted() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)

    turn = await _begin(
        service,
        tenant,
        _key(tenant),
        _payload(_user(f"my email is {EMAIL}")),
        request_id="redact-title",
        header="redact-title-session",
    )
    assert turn is not None
    await _finish(service, turn, content="ok")

    previews = [session.title_preview for session in capture.sessions]
    assert previews
    assert all(EMAIL not in preview for preview in previews)
    assert previews[0] == f"my email is {REDACTED_EMAIL}"


async def test_turns_differing_only_inside_redacted_span_share_a_session() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)
    key = _key(tenant)

    first = _payload(_user(f"my email is {EMAIL}"))
    turn = await _begin(service, tenant, key, first, request_id="redact-prefix-0")
    assert turn is not None
    await _finish(service, turn, content="ok")

    second = _payload(
        _user(f"my email is {SECOND_EMAIL}"),
        _assistant("noted"),
        _user("next"),
    )
    turn = await _begin(service, tenant, key, second, request_id="redact-prefix-1")
    assert turn is not None
    await _finish(service, turn, content="done")

    assert capture.requests[0].message_hashes == [capture.requests[1].message_hashes[0]]
    assert capture.requests[1].match_method == "prefix"
    assert capture.requests[1].session_id == capture.requests[0].session_id
    assert capture.requests[1].turn_index == 2


async def test_dict_keys_and_non_string_scalars_survive_unchanged() -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": f"contact {EMAIL}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        EMAIL: {"type": "string", "maxLength": 12},
                    },
                    "additionalProperties": False,
                    "default": None,
                },
            },
        }
    ]
    turn = await _begin(
        service,
        tenant,
        _key(tenant),
        _payload(_user("hi"), tools=tools),
        request_id="redact-shape",
        header="redact-shape-session",
    )
    assert turn is not None
    await _finish(service, turn, content="ok")

    stored_tools = capture.requests[0].request_params["tools"]
    assert isinstance(stored_tools, list)
    stored_function = stored_tools[0]["function"]
    assert isinstance(stored_function, dict)
    assert stored_function["description"] == f"contact {REDACTED_EMAIL}"

    parameters = stored_function["parameters"]
    assert isinstance(parameters, dict)
    assert EMAIL in parameters["properties"]
    property_schema = parameters["properties"][EMAIL]
    assert property_schema == {"type": "string", "maxLength": 12}
    assert parameters["additionalProperties"] is False
    assert parameters["default"] is None


async def test_redaction_counter_increments_with_rule_label(
    metric_reader: InMemoryMetricReader,
) -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(), repository=capture, tenants=tenants)

    turn = await _begin(
        service,
        tenant,
        _key(tenant),
        _payload(_user(f"{EMAIL} and {EMAIL}")),
        request_id="redact-metric",
        header="redact-metric-session",
    )
    assert turn is not None
    await _finish(service, turn, content=f"reply to {EMAIL}")

    assert _counter_total(metric_reader, "gateway_audit_redactions", rule="email") == 3


async def test_empty_configuration_leaves_content_untouched(
    metric_reader: InMemoryMetricReader,
) -> None:
    tenants = InMemoryTenantRepository()
    tenant = await _tenant(tenants)
    capture = CapturingAuditRepository()
    service = _service(_settings(patterns=""), repository=capture, tenants=tenants)

    turn = await _begin(
        service,
        tenant,
        _key(tenant),
        _payload(_user(f"contact {EMAIL}")),
        request_id="redact-off",
        header="redact-off-session",
    )
    assert turn is not None
    await _finish(service, turn, content=f"wrote to {EMAIL}")

    record = capture.requests[0]
    assert record.request_messages[0]["content"] == f"contact {EMAIL}"
    assert record.response_content == f"wrote to {EMAIL}"
    assert _counter_total(metric_reader, "gateway_audit_redactions") == 0
