from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Mapping
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from llm_gateway.auth.dependencies import AuthenticatedKey, require_api_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, error_payload
from llm_gateway.logging import get_logger
from llm_gateway.providers.base import ProviderError
from llm_gateway.request_context import get_request_id
from llm_gateway.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelListResponse,
    ModelSummary,
)
from llm_gateway.services.audit import (
    AUDIT_SESSION_HEADER,
    AuditService,
    AuditTurn,
    begin_audit_safely,
    record_audit_safely,
)
from llm_gateway.services.chat import ChatService, ChatStream, map_provider_error
from llm_gateway.services.limits import enforce_inference_limits
from llm_gateway.services.usage import (
    USAGE_WRITE_TIMEOUT_SECONDS,
    UsageContext,
    UsageRecorder,
    record_usage_safely,
)

logger = get_logger(__name__)

router = APIRouter()

# The MVP model registry is small, so the full list is returned in one page.
MODEL_LIST_LIMIT = 1000

# Fallback audit timeout for direct calls to ``_stream_sse`` in tests.
DEFAULT_AUDIT_WRITE_TIMEOUT_SECONDS = 2.0


def get_chat_service(container: Annotated[Container, Depends(get_container)]) -> ChatService:
    return ChatService(models=container.models, providers=container.providers)


def get_usage_recorder(
    container: Annotated[Container, Depends(get_container)],
) -> UsageRecorder:
    return UsageRecorder(repository=container.usage, clock=container.clock)


def get_audit_service(
    container: Annotated[Container, Depends(get_container)],
) -> AuditService:
    return AuditService(
        settings=container.settings,
        repository=container.audit,
        tenants=container.tenants,
        clock=container.clock,
    )


def _sse_frame(payload: str) -> bytes:
    return f"data: {payload}\n\n".encode()


def _error_status(exc: BaseException) -> str:
    """Map the final exception to the persisted audit status."""

    if isinstance(exc, ApiError):
        return "upstream_error" if exc.code.value.startswith("upstream_") else "client_error"
    if isinstance(exc, ProviderError):
        return "upstream_error"
    return "error"


def _response_content_text(content: str | list[dict[str, object]] | None) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _merge_tool_call(
    merged: dict[int, dict[str, Any]],
    tool_call: Mapping[str, object],
) -> None:
    raw_index = tool_call.get("index")
    index = raw_index if isinstance(raw_index, int) and not isinstance(raw_index, bool) else 0
    entry = merged.setdefault(index, {"index": index})
    identifier = tool_call.get("id")
    if isinstance(identifier, str):
        entry["id"] = identifier
    call_type = tool_call.get("type")
    if isinstance(call_type, str):
        entry["type"] = call_type
    function = tool_call.get("function")
    if isinstance(function, Mapping):
        target = entry.setdefault("function", {})
        if isinstance(target, dict):
            name = function.get("name")
            if isinstance(name, str) and name:
                target["name"] = name
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                target["arguments"] = str(target.get("arguments", "")) + arguments


def _merged_tool_calls(merged: dict[int, dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not merged:
        return None
    return [merged[index] for index in sorted(merged)]


async def _stream_sse(
    stream: ChatStream,
    *,
    recorder: UsageRecorder,
    context: UsageContext,
    timeout_seconds: float = USAGE_WRITE_TIMEOUT_SECONDS,
    audit_turn: AuditTurn | None = None,
    audit_service: AuditService | None = None,
    audit_timeout_seconds: float = DEFAULT_AUDIT_WRITE_TIMEOUT_SECONDS,
) -> AsyncGenerator[bytes, None]:
    status = "completed"
    content_parts: list[str] = []
    merged_tool_calls: dict[int, dict[str, Any]] = {}
    finish_reason: str | None = None

    try:
        async for chunk in stream.chunks():
            for choice in chunk.choices:
                if choice.index != 0:
                    continue
                delta = choice.delta
                if delta.content:
                    content_parts.append(delta.content)
                if delta.tool_calls:
                    for tool_call in delta.tool_calls:
                        _merge_tool_call(merged_tool_calls, tool_call)
                if finish_reason is None and choice.finish_reason is not None:
                    finish_reason = choice.finish_reason
            yield _sse_frame(chunk.model_dump_json(exclude_none=True))
        yield _sse_frame("[DONE]")
    except ProviderError as exc:
        status = "upstream_error"
        error = map_provider_error(exc)
        request_id = get_request_id() or ""
        logger.warning(
            "stream_provider_error",
            extra={
                "code": error.code.value,
                "request_id": request_id,
                "provider_error": type(exc).__name__,
                "status_code": getattr(exc, "status_code", None),
            },
        )
        yield _sse_frame(json.dumps(error_payload(request_id, error)))
        yield _sse_frame("[DONE]")
    except ApiError as exc:
        status = _error_status(exc)
        raise
    except Exception:
        status = "upstream_error"
        raise
    except (GeneratorExit, asyncio.CancelledError):
        status = "client_disconnected"
        raise
    finally:
        # Client disconnects cancel this generator; shield both the release and
        # the writes so an upstream-billed request is still accounted for.
        with anyio.CancelScope(shield=True):
            try:
                await stream.aclose()
            except Exception as exc:
                logger.warning(
                    "upstream_stream_close_failed",
                    extra={"model_id": stream.model_id, "error": type(exc).__name__},
                )
            finally:
                await record_usage_safely(
                    recorder=recorder,
                    context=context,
                    usage=stream.usage,
                    timeout_seconds=timeout_seconds,
                )
                if audit_turn is not None and audit_service is not None:
                    await record_audit_safely(
                        service=audit_service,
                        turn=audit_turn,
                        provider=stream.provider.value,
                        status=status,
                        response_content="".join(content_parts) or None,
                        response_tool_calls=_merged_tool_calls(merged_tool_calls),
                        finish_reason=finish_reason,
                        usage=stream.usage,
                    )


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    request: Request,
    payload: ChatCompletionRequest,
    api_key: Annotated[AuthenticatedKey, Depends(enforce_inference_limits)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    recorder: Annotated[UsageRecorder, Depends(get_usage_recorder)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> ChatCompletionResponse | StreamingResponse:
    request_id = get_request_id() or ""
    session_header = request.headers.get(AUDIT_SESSION_HEADER)
    audit_turn = await begin_audit_safely(
        service=audit_service,
        tenant_id=api_key.record.tenant_id,
        api_key=api_key.record,
        request_id=request_id,
        model_id=payload.model,
        payload=payload,
        session_header=session_header,
        is_stream=payload.stream,
    )

    if not payload.stream:
        try:
            result = await service.complete(payload)
        except Exception as exc:
            if audit_turn is not None:
                await record_audit_safely(
                    service=audit_service,
                    turn=audit_turn,
                    provider="unknown",
                    status=_error_status(exc),
                )
            raise
        await record_usage_safely(
            recorder=recorder,
            context=UsageContext(
                request_id=request_id,
                tenant_id=api_key.record.tenant_id,
                api_key_id=api_key.record.id,
                model_id=result.model.id,
                provider=result.model.provider,
            ),
            usage=result.response.usage,
        )
        if audit_turn is not None:
            choice = result.response.choices[0]
            await record_audit_safely(
                service=audit_service,
                turn=audit_turn,
                provider=result.model.provider.value,
                status="completed",
                response_content=_response_content_text(choice.message.content),
                response_tool_calls=choice.message.tool_calls,
                finish_reason=choice.finish_reason,
                usage=result.response.usage,
            )
        return result.response

    try:
        stream = await service.open_stream(payload)
    except Exception as exc:
        if audit_turn is not None:
            await record_audit_safely(
                service=audit_service,
                turn=audit_turn,
                provider="unknown",
                status=_error_status(exc),
            )
        raise
    return StreamingResponse(
        _stream_sse(
            stream,
            recorder=recorder,
            context=UsageContext(
                request_id=request_id,
                tenant_id=api_key.record.tenant_id,
                api_key_id=api_key.record.id,
                model_id=stream.model_id,
                provider=stream.provider,
            ),
            audit_turn=audit_turn,
            audit_service=audit_service,
            audit_timeout_seconds=audit_service.settings.audit_write_timeout_seconds,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/v1/models", response_model=ModelListResponse)
async def list_models(
    _: Annotated[AuthenticatedKey, Depends(require_api_key)],
    container: Annotated[Container, Depends(get_container)],
) -> ModelListResponse:
    models, _total = await container.models.list_models(
        limit=MODEL_LIST_LIMIT, offset=0, enabled_only=True
    )
    data = [
        ModelSummary(
            id=model.id,
            created=int(model.created_at.timestamp()),
            owned_by=model.provider.value,
        )
        for model in models
    ]
    return ModelListResponse(data=data)
