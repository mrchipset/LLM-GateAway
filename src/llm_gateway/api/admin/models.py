from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Response

from llm_gateway.auth.dependencies import require_master_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.admin import (
    CreateModelPriceRequest,
    CreateModelRequest,
    ModelDetail,
    ModelListResponse,
    ModelPriceDetail,
    ModelPriceListResponse,
)
from llm_gateway.storage.repositories import (
    DuplicateModelError,
    DuplicatePriceError,
    ModelConfig,
    ModelPrice,
)

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


def _price_detail(price: ModelPrice) -> ModelPriceDetail:
    return ModelPriceDetail(
        id=price.id,
        model_id=price.model_id,
        input_per_million=price.input_per_million,
        cached_input_per_million=price.cached_input_per_million,
        output_per_million=price.output_per_million,
        currency=price.currency,
        effective_from=price.effective_from,
        created_at=price.created_at,
    )


def _model_not_found(model_id: str) -> ApiError:
    return ApiError(
        status_code=404,
        code=ApiErrorCode.MODEL_NOT_FOUND,
        message=f"Model '{model_id}' was not found",
        error_type="invalid_request_error",
        param="model_id",
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
        raise _model_not_found(model_id)
    return Response(status_code=204)


@router.post(
    "/models/{model_id}/prices",
    response_model=ModelPriceDetail,
    status_code=201,
)
async def create_model_price(
    model_id: str,
    payload: CreateModelPriceRequest,
    container: Annotated[Container, Depends(get_container)],
) -> ModelPriceDetail:
    if await container.models.get_model(model_id) is None:
        raise _model_not_found(model_id)

    if payload.effective_from is not None and (
        payload.effective_from.tzinfo is None or payload.effective_from.utcoffset() is None
    ):
        raise ApiError.invalid_request(
            "effective_from must be timezone-aware",
            param="effective_from",
        )

    now = container.clock.now()
    price = ModelPrice(
        id=uuid4(),
        model_id=model_id,
        input_per_million=payload.input_per_million,
        cached_input_per_million=payload.cached_input_per_million,
        output_per_million=payload.output_per_million,
        currency=container.settings.billing_currency,
        effective_from=payload.effective_from if payload.effective_from is not None else now,
        created_at=now,
    )
    try:
        created = await container.prices.create_price(price)
    except DuplicatePriceError as exc:
        raise ApiError(
            status_code=409,
            code=ApiErrorCode.DUPLICATE_PRICE,
            message="A price with this effective_from already exists for the model",
            error_type="invalid_request_error",
            param="effective_from",
        ) from exc
    return _price_detail(created)


@router.get("/models/{model_id}/prices", response_model=ModelPriceListResponse)
async def list_model_prices(
    model_id: str,
    container: Annotated[Container, Depends(get_container)],
    limit: PaginationLimit = 50,
    offset: PaginationOffset = 0,
) -> ModelPriceListResponse:
    if await container.models.get_model(model_id) is None:
        raise _model_not_found(model_id)

    items, total = await container.prices.list_prices(
        model_id=model_id,
        limit=limit,
        offset=offset,
    )
    return ModelPriceListResponse(
        items=[_price_detail(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
