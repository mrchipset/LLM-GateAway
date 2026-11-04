from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Response

from llm_gateway.auth.admin_auth import AdminPrincipal
from llm_gateway.auth.admin_deps import current_admin, require_write_access
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.schemas.admin import (
    CreateDeploymentRequest,
    DeploymentDetail,
    DeploymentListResponse,
    UpdateDeploymentRequest,
)
from llm_gateway.services.admin_audit import (
    deployment_snapshot,
    record_admin_event_safely,
)
from llm_gateway.storage.repositories import (
    DuplicateDeploymentError,
    ModelDeployment,
    UnknownModelError,
)

router = APIRouter(tags=["admin-deployments"])


def _detail(deployment: ModelDeployment) -> DeploymentDetail:
    return DeploymentDetail(
        id=deployment.id,
        model_id=deployment.model_id,
        name=deployment.name,
        provider=deployment.provider,
        upstream_model=deployment.upstream_model,
        weight=deployment.weight,
        enabled=deployment.enabled,
        credential_env=deployment.credential_env,
        base_url=deployment.base_url,
        created_at=deployment.created_at,
    )


def _model_not_found(model_id: str) -> ApiError:
    return ApiError(
        status_code=404,
        code=ApiErrorCode.MODEL_NOT_FOUND,
        message=f"Model '{model_id}' was not found",
        error_type="invalid_request_error",
        param="model_id",
    )


def _deployment_not_found(deployment_id: UUID) -> ApiError:
    return ApiError(
        status_code=404,
        code=ApiErrorCode.DEPLOYMENT_NOT_FOUND,
        message=f"Deployment '{deployment_id}' was not found",
        error_type="invalid_request_error",
    )


def _require_provider_configured(
    container: Container,
    *,
    provider: object,
    credential_env: str | None,
    base_url: str | None,
) -> None:
    from llm_gateway.providers.base import ProviderName

    if credential_env is not None or base_url is not None:
        return
    if isinstance(provider, ProviderName) and container.providers.is_configured(provider):
        return
    raise ApiError(
        status_code=400,
        code=ApiErrorCode.PROVIDER_NOT_CONFIGURED,
        message="Provider is not configured; set a credential_env or register the provider",
        error_type="invalid_request_error",
        param="provider",
    )


@router.get("/models/{model_id}/deployments", response_model=DeploymentListResponse)
async def list_deployments(
    model_id: str,
    _: Annotated[AdminPrincipal, Depends(current_admin)],
    container: Annotated[Container, Depends(get_container)],
) -> DeploymentListResponse:
    if await container.models.get_model(model_id) is None:
        raise _model_not_found(model_id)
    deployments = await container.deployments.list_deployments(model_id)
    return DeploymentListResponse(
        model_id=model_id,
        items=[_detail(deployment) for deployment in deployments],
    )


@router.post(
    "/models/{model_id}/deployments",
    response_model=DeploymentDetail,
    status_code=201,
)
async def create_deployment(
    model_id: str,
    payload: CreateDeploymentRequest,
    principal: Annotated[AdminPrincipal, Depends(require_write_access)],
    container: Annotated[Container, Depends(get_container)],
) -> DeploymentDetail:
    if await container.models.get_model(model_id) is None:
        raise _model_not_found(model_id)
    _require_provider_configured(
        container,
        provider=payload.provider,
        credential_env=payload.credential_env,
        base_url=payload.base_url,
    )

    deployment = ModelDeployment(
        id=uuid4(),
        model_id=model_id,
        name=payload.name,
        provider=payload.provider,
        upstream_model=payload.upstream_model,
        weight=payload.weight,
        enabled=payload.enabled,
        created_at=container.clock.now(),
        credential_env=payload.credential_env,
        base_url=payload.base_url,
    )
    try:
        created = await container.deployments.create_deployment(deployment)
    except DuplicateDeploymentError as exc:
        raise ApiError(
            status_code=409,
            code=ApiErrorCode.DUPLICATE_DEPLOYMENT,
            message=f"Deployment '{payload.name}' already exists for this model",
            error_type="invalid_request_error",
            param="name",
        ) from exc
    except UnknownModelError as exc:  # pragma: no cover - guarded above
        raise _model_not_found(model_id) from exc

    await record_admin_event_safely(
        container=container,
        principal=principal,
        action="model_deployment.created",
        target_type="model",
        target_id=model_id,
        after=deployment_snapshot(created),
    )
    return _detail(created)


@router.patch("/deployments/{deployment_id}", response_model=DeploymentDetail)
async def update_deployment(
    deployment_id: UUID,
    payload: UpdateDeploymentRequest,
    principal: Annotated[AdminPrincipal, Depends(require_write_access)],
    container: Annotated[Container, Depends(get_container)],
) -> DeploymentDetail:
    existing = await container.deployments.get_deployment(deployment_id)
    if existing is None:
        raise _deployment_not_found(deployment_id)

    provided = payload.model_fields_set
    try:
        updated = await container.deployments.update_deployment(
            deployment_id,
            name=payload.name,
            upstream_model=payload.upstream_model,
            weight=payload.weight,
            enabled=payload.enabled,
            credential_env=payload.credential_env,
            base_url=payload.base_url,
            replace_credential_env="credential_env" in provided,
            replace_base_url="base_url" in provided,
        )
    except DuplicateDeploymentError as exc:
        raise ApiError(
            status_code=409,
            code=ApiErrorCode.DUPLICATE_DEPLOYMENT,
            message=f"Deployment '{payload.name}' already exists for this model",
            error_type="invalid_request_error",
            param="name",
        ) from exc

    if updated is None:
        raise _deployment_not_found(deployment_id)

    await record_admin_event_safely(
        container=container,
        principal=principal,
        action="model_deployment.updated",
        target_type="model",
        target_id=existing.model_id,
        before=deployment_snapshot(existing),
        after=deployment_snapshot(updated),
    )
    return _detail(updated)


@router.delete("/deployments/{deployment_id}", status_code=204)
async def delete_deployment(
    deployment_id: UUID,
    principal: Annotated[AdminPrincipal, Depends(require_write_access)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    existing = await container.deployments.get_deployment(deployment_id)
    deleted = await container.deployments.delete_deployment(deployment_id)
    if not deleted:
        raise _deployment_not_found(deployment_id)

    if existing is not None:
        await record_admin_event_safely(
            container=container,
            principal=principal,
            action="model_deployment.deleted",
            target_type="model",
            target_id=existing.model_id,
            before=deployment_snapshot(existing),
        )
    return Response(status_code=204)
