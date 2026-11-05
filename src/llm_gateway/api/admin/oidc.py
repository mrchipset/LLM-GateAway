"""Admin SSO endpoints: start the OIDC flow and handle the callback."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from llm_gateway.api.admin.auth import (
    _set_session_cookies,  # same cookie contract as password login
)
from llm_gateway.auth.admin_deps import build_auth_service
from llm_gateway.auth.passwords import hash_password
from llm_gateway.config import Environment, Settings
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.logging import get_logger
from llm_gateway.services.oidc import OIDCIdentity, OIDCService
from llm_gateway.storage.repositories import AdminUser, DuplicateAdminError

logger = get_logger(__name__)

router = APIRouter(tags=["admin-oidc"])

STATE_COOKIE = "gw_oidc_state"
NONCE_COOKIE = "gw_oidc_nonce"
VERIFIER_COOKIE = "gw_oidc_verifier"
COOKIE_PATH = "/api/v1/auth/oidc"
COOKIE_MAX_AGE = 600


def _enabled(container: Container) -> OIDCService:
    service = container.oidc
    if not container.settings.oidc_enabled or service is None:
        raise ApiError(
            status_code=404,
            code=ApiErrorCode.NOT_FOUND,
            message="OIDC is not enabled",
            error_type="invalid_request_error",
        )
    return service


def _secure(settings: Settings) -> bool:
    return settings.environment is Environment.PRODUCTION


def _set_flow_cookie(response: RedirectResponse, *, name: str, value: str, secure: bool) -> None:
    response.set_cookie(
        name,
        value,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path=COOKIE_PATH,
    )


def _clear_flow_cookies(response: RedirectResponse, *, secure: bool) -> None:
    for name in (STATE_COOKIE, NONCE_COOKIE, VERIFIER_COOKIE):
        response.delete_cookie(name, path=COOKIE_PATH, httponly=True, samesite="lax", secure=secure)


@router.get("/auth/oidc/status")
async def oidc_status(
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, bool]:
    enabled = container.settings.oidc_enabled and container.oidc is not None
    return {"enabled": enabled}


@router.get("/auth/oidc/start")
async def oidc_start(
    container: Annotated[Container, Depends(get_container)],
) -> RedirectResponse:
    service = _enabled(container)
    settings = container.settings
    secure = _secure(settings)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )

    url = await service.authorize_url(state=state, nonce=nonce, code_challenge=challenge)
    response = RedirectResponse(url, status_code=302)
    _set_flow_cookie(response, name=STATE_COOKIE, value=state, secure=secure)
    _set_flow_cookie(response, name=NONCE_COOKIE, value=nonce, secure=secure)
    _set_flow_cookie(response, name=VERIFIER_COOKIE, value=verifier, secure=secure)
    return response


@router.get("/auth/oidc/callback")
async def oidc_callback(
    request: Request,
    container: Annotated[Container, Depends(get_container)],
) -> RedirectResponse:
    service = _enabled(container)
    settings = container.settings
    secure = _secure(settings)

    state = request.query_params.get("state", "")
    code = request.query_params.get("code", "")
    expected_state = request.cookies.get(STATE_COOKIE)
    nonce = request.cookies.get(NONCE_COOKIE)
    verifier = request.cookies.get(VERIFIER_COOKIE)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise ApiError(
            status_code=400,
            code=ApiErrorCode.OIDC_STATE_INVALID,
            message="OIDC state is missing or does not match",
            error_type="invalid_request_error",
        )
    if not code or nonce is None or verifier is None:
        raise ApiError(
            status_code=400,
            code=ApiErrorCode.OIDC_STATE_INVALID,
            message="OIDC callback is missing the code or flow cookies",
            error_type="invalid_request_error",
        )

    try:
        identity = await service.exchange(code=code, code_verifier=verifier, nonce=nonce)
    except Exception as exc:  # OIDCError and transport failures share one browser path
        code_value = getattr(exc, "code", "oidc_failed")
        logger.warning(
            "oidc_exchange_failed",
            extra={"code": code_value, "error": type(exc).__name__},
        )
        response = RedirectResponse(f"/?sso_error={code_value}", status_code=303)
        _clear_flow_cookies(response, secure=secure)
        return response

    admin = await _resolve_admin(container, identity)
    if admin is None:
        response = RedirectResponse("/?sso_error=admin_not_provisioned", status_code=303)
        _clear_flow_cookies(response, secure=secure)
        return response
    if not admin.active:
        response = RedirectResponse("/?sso_error=admin_inactive", status_code=303)
        _clear_flow_cookies(response, secure=secure)
        return response

    now: datetime = container.clock.now()
    result = await build_auth_service(container).issue_session(admin, now=now)
    response = RedirectResponse("/", status_code=303)
    _set_session_cookies(
        response,
        settings=settings,
        token=result.token,
        csrf_token=result.csrf_token,
    )
    _clear_flow_cookies(response, secure=secure)
    return response


async def _resolve_admin(container: Container, identity: OIDCIdentity) -> AdminUser | None:
    existing = await container.admins.get_admin_by_oidc_subject(identity.subject)
    if existing is not None:
        return existing
    if not container.settings.oidc_jit_provisioning:
        return None
    now = container.clock.now()
    for username in (identity.username, identity.fallback_username):
        admin = AdminUser(
            id=uuid4(),
            username=username,
            display_name=identity.display_name,
            role=identity.role,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            active=True,
            created_at=now,
            updated_at=now,
            password_changed_at=now,
            oidc_subject=identity.subject,
        )
        try:
            return await container.admins.create_admin(admin)
        except DuplicateAdminError:
            continue
    logger.warning("oidc_provisioning_conflict", extra={"subject": identity.subject})
    return None
