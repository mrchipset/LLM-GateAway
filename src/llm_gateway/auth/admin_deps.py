"""Request dependencies for the management plane.

Authentication sources, in order: the admin session cookie, then the break-glass
master key. The master key is only accepted while ``master_key_enabled`` is true and
always maps to the owner role, because that is what it meant before identities
existed.

CSRF: cookie-authenticated state-changing requests must echo the session's CSRF token
in ``x-csrf-token``. Master-key callers are exempt because the token is not ambient.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from llm_gateway.auth.admin_auth import (
    AdminAuthService,
    AdminPrincipal,
    csrf_matches,
    master_principal,
)
from llm_gateway.auth.keys import verify_master_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.storage.repositories import AdminActorType

SESSION_COOKIE = "gw_admin_session"
CSRF_COOKIE = "gw_admin_csrf"
CSRF_HEADER = "x-csrf-token"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def build_auth_service(container: Container) -> AdminAuthService:
    return AdminAuthService(
        admins=container.admins,
        sessions=container.admin_sessions,
        throttle=container.login_throttle,
        clock=container.clock,
        session_ttl_hours=container.settings.session_ttl_hours,
    )


def _unauthorized(message: str = "Management authentication is required") -> ApiError:
    return ApiError(
        status_code=401,
        code=ApiErrorCode.ADMIN_AUTH_REQUIRED,
        message=message,
        error_type="authentication_error",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(message: str) -> ApiError:
    return ApiError(
        status_code=403,
        code=ApiErrorCode.ADMIN_FORBIDDEN,
        message=message,
        error_type="permission_error",
    )


async def current_admin(
    request: Request,
    container: Annotated[Container, Depends(get_container)],
) -> AdminPrincipal:
    now = container.clock.now()
    service = build_auth_service(container)

    token = request.cookies.get(SESSION_COOKIE)
    if token:
        principal = await service.authenticate(token, now=now)
        if principal is None:
            raise _unauthorized("The admin session is invalid or expired")

        if request.method not in _SAFE_METHODS:
            session = await container.admin_sessions.get_session_by_token_hash(
                __import__("hashlib").sha256(token.encode("utf-8")).hexdigest()
            )
            presented = request.headers.get(CSRF_HEADER)
            if session is None or not csrf_matches(session.csrf_hash, presented):
                raise ApiError(
                    status_code=403,
                    code=ApiErrorCode.CSRF_FAILED,
                    message="The CSRF token is missing or invalid",
                    error_type="permission_error",
                )
        return principal

    authorization = request.headers.get("authorization")
    if authorization is not None:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            candidate = parts[1]
            if container.settings.master_key_enabled and verify_master_key(
                candidate, container.settings.master_key
            ):
                return master_principal()

    raise _unauthorized()


async def require_write_access(
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> AdminPrincipal:
    if not principal.can_write:
        raise _forbidden("This role cannot modify configuration")
    return principal


async def require_owner(
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> AdminPrincipal:
    if not principal.can_manage_admins:
        raise _forbidden("Only an owner can manage admin accounts")
    return principal


async def require_audit_read(
    principal: Annotated[AdminPrincipal, Depends(current_admin)],
) -> AdminPrincipal:
    if not principal.can_read_audit:
        raise _forbidden("This role cannot read the admin audit trail")
    return principal


def is_master(principal: AdminPrincipal) -> bool:
    return principal.actor_type is AdminActorType.MASTER
