from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from llm_gateway.auth.admin_auth import (
    AdminPrincipal,
    LoginThrottledError,
    normalize_username,
)
from llm_gateway.auth.admin_deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    build_auth_service,
    current_admin,
)
from llm_gateway.config import Environment, Settings
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.logging import get_logger
from llm_gateway.metrics import current_metrics
from llm_gateway.schemas.admin import (
    CurrentAdminResponse,
    LoginRequest,
    LoginResponse,
)

logger = get_logger(__name__)

router = APIRouter(tags=["admin-auth"])

LOGIN_THROTTLE_RETRY_AFTER = "900"


def _secure_cookies(settings: Settings) -> bool:
    return settings.environment is Environment.PRODUCTION


def _set_session_cookies(
    response: Response,
    *,
    settings: Settings,
    token: str,
    csrf_token: str,
) -> None:
    max_age = settings.session_ttl_hours * 3600
    secure = _secure_cookies(settings)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    # Readable by the console so it can echo the token in the CSRF header.
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=secure,
        path="/",
    )


def _clear_session_cookies(response: Response, *, settings: Settings) -> None:
    secure = _secure_cookies(settings)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=secure)
    response.delete_cookie(CSRF_COOKIE, path="/", httponly=False, samesite="lax", secure=secure)


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    container: Annotated[Container, Depends(get_container)],
) -> LoginResponse:
    service = build_auth_service(container)
    now = container.clock.now()
    try:
        result = await service.login(
            username=payload.username,
            password=payload.password,
            now=now,
        )
    except LoginThrottledError as exc:
        raise ApiError(
            status_code=429,
            code=ApiErrorCode.LOGIN_THROTTLED,
            message="Too many failed login attempts; try again later",
            error_type="rate_limit_error",
            headers={"Retry-After": LOGIN_THROTTLE_RETRY_AFTER},
        ) from exc

    if result is None:
        logger.warning(
            "admin_login_failed",
            extra={"username": normalize_username(payload.username)},
        )
        current_metrics().rejections.add(1, {"reason": "admin_login"})
        raise ApiError(
            status_code=401,
            code=ApiErrorCode.INVALID_CREDENTIALS,
            message="Invalid username or password",
            error_type="authentication_error",
        )

    _set_session_cookies(
        response,
        settings=container.settings,
        token=result.token,
        csrf_token=result.csrf_token,
    )
    logger.info(
        "admin_login_succeeded",
        extra={"username": result.admin.username, "role": str(result.admin.role)},
    )
    return LoginResponse(
        username=result.admin.username,
        display_name=result.admin.display_name,
        role=result.admin.role,
        actor_type=result.admin
        and __import__(
            "llm_gateway.storage.repositories", fromlist=["AdminActorType"]
        ).AdminActorType.ADMIN,
        expires_at=result.session.expires_at,
    )


@router.post("/auth/logout", status_code=204)
async def logout(
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    await build_auth_service(container).logout(principal, now=container.clock.now())
    response = Response(status_code=204)
    _clear_session_cookies(response, settings=container.settings)
    return response


@router.get("/auth/me", response_model=CurrentAdminResponse)
async def me(
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> CurrentAdminResponse:
    return CurrentAdminResponse(
        actor_type=principal.actor_type,
        name=principal.name,
        role=principal.role,
        admin_id=principal.admin_id,
    )
