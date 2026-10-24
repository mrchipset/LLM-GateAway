from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from llm_gateway.auth.dependencies import AuthenticatedKey, require_api_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import error_payload
from llm_gateway.logging import get_logger
from llm_gateway.providers.base import ProviderError
from llm_gateway.request_context import get_request_id
from llm_gateway.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelListResponse,
    ModelSummary,
)
from llm_gateway.services.chat import ChatService, ChatStream, map_provider_error

logger = get_logger(__name__)

router = APIRouter()

# The MVP model registry is small, so the full list is returned in one page.
MODEL_LIST_LIMIT = 1000


def get_chat_service(container: Annotated[Container, Depends(get_container)]) -> ChatService:
    return ChatService(models=container.models, providers=container.providers)


def _sse_frame(payload: str) -> bytes:
    return f"data: {payload}\n\n".encode()


async def _stream_sse(stream: ChatStream) -> AsyncGenerator[bytes, None]:
    try:
        async for chunk in stream.chunks():
            yield _sse_frame(chunk.model_dump_json(exclude_none=True))
        yield _sse_frame("[DONE]")
    except ProviderError as exc:
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
    finally:
        # Client disconnects cancel this generator; shield the release so the
        # upstream connection is always closed.
        with anyio.CancelScope(shield=True):
            await stream.aclose()


@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    payload: ChatCompletionRequest,
    _: Annotated[AuthenticatedKey, Depends(require_api_key)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatCompletionResponse | StreamingResponse:
    if not payload.stream:
        return await service.complete(payload)

    stream = await service.open_stream(payload)
    return StreamingResponse(
        _stream_sse(stream),
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
