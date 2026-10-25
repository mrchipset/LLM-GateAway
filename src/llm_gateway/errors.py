from __future__ import annotations

import uuid
from collections.abc import Mapping
from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from llm_gateway.logging import get_logger
from llm_gateway.request_context import REQUEST_ID_HEADER, get_request_id

logger = get_logger(__name__)


class ApiErrorCode(StrEnum):
    INVALID_REQUEST_BODY = "invalid_request_body"
    MISSING_API_KEY = "missing_api_key"
    INVALID_API_KEY = "invalid_api_key"
    MASTER_KEY_REQUIRED = "master_key_required"
    MASTER_KEY_NOT_ALLOWED = "master_key_not_allowed"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMITED = "rate_limited"
    TENANT_QUOTA_EXCEEDED = "tenant_quota_exceeded"
    MODEL_NOT_FOUND = "model_not_found"
    MODEL_DISABLED = "model_disabled"
    DUPLICATE_MODEL = "duplicate_model"
    DUPLICATE_TENANT = "duplicate_tenant"
    TENANT_NOT_FOUND = "tenant_not_found"
    KEY_NOT_FOUND = "key_not_found"
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    UPSTREAM_AUTH_FAILED = "upstream_auth_failed"
    UPSTREAM_RATE_LIMITED = "upstream_rate_limited"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    UPSTREAM_REJECTED = "upstream_rejected"
    UPSTREAM_INVALID_RESPONSE = "upstream_invalid_response"
    INTERNAL_ERROR = "internal_error"


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: ApiErrorCode,
        message: str,
        error_type: str,
        param: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.error_type = error_type
        self.param = param
        self.headers = headers

    @classmethod
    def invalid_request(cls, message: str, *, param: str | None = None) -> ApiError:
        return cls(
            status_code=400,
            code=ApiErrorCode.INVALID_REQUEST_BODY,
            message=message,
            error_type="invalid_request_error",
            param=param,
        )

    @classmethod
    def unauthorized(
        cls,
        message: str,
        *,
        code: ApiErrorCode,
        headers: dict[str, str] | None = None,
    ) -> ApiError:
        return cls(
            status_code=401,
            code=code,
            message=message,
            error_type="authentication_error",
            headers=headers,
        )

    @classmethod
    def not_found(cls, message: str) -> ApiError:
        return cls(
            status_code=404,
            code=ApiErrorCode.NOT_FOUND,
            message=message,
            error_type="invalid_request_error",
        )

    @classmethod
    def internal(cls, message: str = "Internal server error") -> ApiError:
        return cls(
            status_code=500,
            code=ApiErrorCode.INTERNAL_ERROR,
            message=message,
            error_type="server_error",
        )


def error_payload(request_id: str, error: ApiError) -> dict[str, object]:
    return {
        "error": {
            "message": error.message,
            "type": error.error_type,
            "param": error.param,
            "code": error.code.value,
            "request_id": request_id,
        }
    }


def _resolve_request_id(request: Request) -> str:
    request_id = get_request_id()
    if request_id is not None:
        return request_id

    state = request.scope.get("state")
    if isinstance(state, dict):
        stored = state.get("request_id")
        if isinstance(stored, str) and stored:
            return stored

    return uuid.uuid4().hex


def _response(
    request_id: str,
    error: ApiError,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=error.status_code,
        content=error_payload(request_id, error),
        headers=response_headers,
    )


async def _api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise exc
    request_id = _resolve_request_id(request)
    return _response(request_id, exc, exc.headers)


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    request_id = _resolve_request_id(request)
    errors = exc.errors()
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first["loc"])
        message = f"Invalid request body: {location}: {first['msg']}"
    else:
        message = "Invalid request body"

    error = ApiError(
        status_code=400,
        code=ApiErrorCode.INVALID_REQUEST_BODY,
        message=message,
        error_type="invalid_request_error",
    )
    return _response(request_id, error)


async def _http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    request_id = _resolve_request_id(request)

    if exc.status_code == 401:
        code = ApiErrorCode.INVALID_API_KEY
        error_type = "authentication_error"
    elif exc.status_code == 403:
        code = ApiErrorCode.PERMISSION_DENIED
        error_type = "permission_error"
    elif exc.status_code == 429:
        code = ApiErrorCode.RATE_LIMITED
        error_type = "rate_limit_error"
    elif exc.status_code == 404:
        code = ApiErrorCode.NOT_FOUND
        error_type = "invalid_request_error"
    elif exc.status_code == 405:
        code = ApiErrorCode.METHOD_NOT_ALLOWED
        error_type = "invalid_request_error"
    elif exc.status_code >= 500:
        code = ApiErrorCode.INTERNAL_ERROR
        error_type = "server_error"
    else:
        code = ApiErrorCode.INVALID_REQUEST_BODY
        error_type = "invalid_request_error"

    if exc.status_code >= 500:
        message = "Internal server error"
    elif isinstance(exc.detail, str):
        message = exc.detail
    else:
        message = "Request failed"

    error = ApiError(
        status_code=exc.status_code,
        code=code,
        message=message,
        error_type=error_type,
    )
    return _response(request_id, error, headers=exc.headers)


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _resolve_request_id(request)
    logger.exception(
        "unhandled_exception",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        },
        exc_info=exc,
    )
    return _response(request_id, ApiError.internal())


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
