from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from llm_gateway.auth.keys import hash_api_key, is_key_active, verify_master_key
from llm_gateway.container import Container, get_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.logging import get_logger
from llm_gateway.storage.repositories import ApiKeyRecord

logger = get_logger(__name__)

_WWW_AUTHENTICATE = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True, slots=True)
class AuthenticatedKey:
    record: ApiKeyRecord


def parse_bearer_token(header_value: str | None) -> str | None:
    """Extract the token from a ``Bearer`` Authorization header, if well formed."""
    if header_value is None:
        return None

    parts = header_value.split()
    if len(parts) != 2:
        return None

    scheme, token = parts
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _unauthorized(message: str, code: ApiErrorCode) -> ApiError:
    return ApiError.unauthorized(message, code=code, headers=dict(_WWW_AUTHENTICATE))


async def require_api_key(
    request: Request,
    container: Annotated[Container, Depends(get_container)],
) -> AuthenticatedKey:
    token = parse_bearer_token(request.headers.get("authorization"))
    if token is None:
        raise _unauthorized("Missing API key", ApiErrorCode.MISSING_API_KEY)

    if verify_master_key(token, container.settings.master_key):
        raise _unauthorized(
            "Master key cannot be used for inference",
            ApiErrorCode.MASTER_KEY_NOT_ALLOWED,
        )

    now = container.clock.now()
    record = await container.api_keys.get_key_by_hash(hash_api_key(token))
    if record is None or not is_key_active(record, now):
        raise _unauthorized("Invalid API key", ApiErrorCode.INVALID_API_KEY)

    try:
        await container.api_keys.touch_last_used(record.id, now)
    except Exception:
        # Best effort: a storage failure must not reject an authenticated request.
        logger.warning(
            "api_key_touch_failed",
            extra={"key_id": str(record.id)},
            exc_info=True,
        )

    return AuthenticatedKey(record=record)


async def require_master_key(
    request: Request,
    container: Annotated[Container, Depends(get_container)],
) -> None:
    token = parse_bearer_token(request.headers.get("authorization"))
    if token is None:
        raise _unauthorized("Master key is required", ApiErrorCode.MASTER_KEY_REQUIRED)

    if not verify_master_key(token, container.settings.master_key):
        raise _unauthorized("A valid master key is required", ApiErrorCode.INVALID_API_KEY)
