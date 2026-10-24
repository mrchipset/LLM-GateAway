from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from llm_gateway.auth.dependencies import require_master_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.admin import (
    CreateModelRequest,
    ModelDetail,
    ModelListResponse,
)
from llm_gateway.storage.repositories import DuplicateModelError, ModelConfig

router = APIRouter(dependencies=[Depends(require_master_key)])

PaginationLimit = Annotated[int, Query(ge=1, le=100)]
PaginationOffset = Annotated[int, Query(ge=0)]


def _detail(model: ModelConfig) -> ModelDetail:
    return ModelDetail(
        id=model.id,
        provider=model.provider,
        upstream_model=model.upstream_model,
        enabled=model.enabled,
        created_at=model.created_at,
    )


@router.post("/models", response_model=ModelDetail, status_code=201)
async def create_model(
    payload: CreateModelRequest,
    container: Annotated[Container, Depends(get_container)],
) -> ModelDetail:
    if not container.providers.is_configured(payload.provider):
        raise ApiError(
            status_code=400,
            code=ApiErrorCode.PROVIDER_NOT_CONFIGURED,
            message=f"Provider '{payload.provider.value}' is not configured",
            error_type="invalid_request_error",
            param="provider",
        )

    model = ModelConfig(
        id=payload.id,
        provider=payload.provider,
        upstream_model=payload.upstream_model,
        created_at=container.clock.now(),
        enabled=payload.enabled,
    )
    try:
        created = await container.models.create_model(model)
    except DuplicateModelError as exc:
        raise ApiError(
            status_code=409,
            code=ApiErrorCode.DUPLICATE_MODEL,
            message=f"Model '{payload.id}' already exists",
            error_type="invalid_request_error",
            param="id",
        ) from exc
    return _detail(created)


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    container: Annotated[Container, Depends(get_container)],
    limit: PaginationLimit = 50,
    offset: PaginationOffset = 0,
) -> ModelListResponse:
    models, total = await container.models.list_models(limit=limit, offset=offset)
    return ModelListResponse(
        items=[_detail(model) for model in models],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(
    model_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    deleted = await container.models.delete_model(model_id)
    if not deleted:
        raise ApiError(
            status_code=404,
            code=ApiErrorCode.MODEL_NOT_FOUND,
            message=f"Model '{model_id}' was not found",
            error_type="invalid_request_error",
        )
    return Response(status_code=204)
