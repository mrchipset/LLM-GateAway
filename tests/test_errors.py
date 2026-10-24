from __future__ import annotations

import logging
from collections.abc import Mapping

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from llm_gateway.errors import ApiError, ApiErrorCode, register_error_handlers
from llm_gateway.request_context import REQUEST_ID_HEADER


def _error_body(response: httpx.Response) -> dict[str, object]:
    body = response.json()
    error = body["error"]
    assert isinstance(error, dict), "error payload must be an object"
    return error


def _parse_route_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/parse")
    def parse(payload: dict[str, str]) -> dict[str, str]:
        return payload

    return app


def _api_error_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise ApiError.unauthorized(
            "Invalid API key",
            code=ApiErrorCode.INVALID_API_KEY,
        )

    return app


def _http_error_app(
    status_code: int,
    detail: str | dict[str, str],
    headers: Mapping[str, str] | None = None,
) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/http-error")
    def http_error() -> None:
        raise HTTPException(status_code=status_code, detail=detail, headers=headers)

    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.get(path)


async def _post_json(app: FastAPI, path: str, content: bytes) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.post(
            path,
            content=content,
            headers={"content-type": "application/json"},
        )


async def test_unknown_route_returns_stable_error(client: httpx.AsyncClient) -> None:
    response = await client.get("/does-not-exist")

    assert response.status_code == 404
    error = _error_body(response)
    assert error["type"] == "invalid_request_error"
    assert error["code"] == ApiErrorCode.NOT_FOUND.value
    assert error["request_id"] == response.headers[REQUEST_ID_HEADER]


async def test_method_not_allowed_is_mapped_to_stable_code() -> None:
    response = await _get(_parse_route_app(), "/parse")

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
    error = _error_body(response)
    assert error["type"] == "invalid_request_error"
    assert error["code"] == ApiErrorCode.METHOD_NOT_ALLOWED.value


async def test_http_unauthorized_preserves_headers_and_code() -> None:
    response = await _get(
        _http_error_app(
            401,
            "Missing bearer token",
            {"WWW-Authenticate": "Bearer"},
        ),
        "/http-error",
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    error = _error_body(response)
    assert error["code"] == ApiErrorCode.INVALID_API_KEY.value
    assert error["type"] == "authentication_error"


@pytest.mark.parametrize(
    ("status_code", "code", "error_type"),
    [
        (403, ApiErrorCode.PERMISSION_DENIED, "permission_error"),
        (429, ApiErrorCode.RATE_LIMITED, "rate_limit_error"),
    ],
)
async def test_http_exception_auth_semantics(
    status_code: int,
    code: ApiErrorCode,
    error_type: str,
) -> None:
    response = await _get(_http_error_app(status_code, "denied"), "/http-error")

    assert response.status_code == status_code
    error = _error_body(response)
    assert error["code"] == code.value
    assert error["type"] == error_type


async def test_http_exception_non_string_detail_is_not_echoed() -> None:
    response = await _get(
        _http_error_app(400, {"internal": "x"}),
        "/http-error",
    )

    assert response.status_code == 400
    error = _error_body(response)
    assert error["message"] == "Request failed"
    assert "internal" not in response.text


async def test_invalid_json_body_returns_invalid_request_body() -> None:
    raw_body = b'{"name": '
    response = await _post_json(_parse_route_app(), "/parse", raw_body)

    assert response.status_code == 400
    error = _error_body(response)
    assert error["type"] == "invalid_request_error"
    assert error["code"] == ApiErrorCode.INVALID_REQUEST_BODY.value
    message = error["message"]
    assert isinstance(message, str)
    assert message.startswith("Invalid request body")
    assert raw_body.decode() not in response.text


async def test_api_error_raised_in_route_uses_documented_payload() -> None:
    response = await _get(_api_error_app(), "/boom")

    assert response.status_code == 401
    error = _error_body(response)
    assert error["message"] == "Invalid API key"
    assert error["type"] == "authentication_error"
    assert error["param"] is None
    assert error["code"] == ApiErrorCode.INVALID_API_KEY.value
    assert error["request_id"] == response.headers[REQUEST_ID_HEADER]


@pytest.mark.parametrize("status_code", [500, 503])
async def test_server_http_errors_do_not_leak_detail(status_code: int) -> None:
    response = await _get(
        _http_error_app(status_code, "upstream secret detail"),
        "/http-error",
    )

    assert response.status_code == status_code
    error = _error_body(response)
    assert error["code"] == ApiErrorCode.INTERNAL_ERROR.value
    assert error["type"] == "server_error"
    assert "upstream secret detail" not in response.text


async def test_unhandled_exception_returns_generic_internal_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="llm_gateway.errors")

    app = FastAPI()
    register_error_handlers(app)

    @app.get("/explode")
    def explode() -> None:
        raise RuntimeError("db secret at internal-host")

    response = await _get(app, "/explode")

    assert response.status_code == 500
    error = _error_body(response)
    assert error["code"] == ApiErrorCode.INTERNAL_ERROR.value
    assert error["type"] == "server_error"
    request_id = response.headers[REQUEST_ID_HEADER]
    assert error["request_id"] == request_id
    assert "secret" not in response.text
    assert "internal-host" not in response.text

    records = [
        record
        for record in caplog.records
        if record.name == "llm_gateway.errors" and record.getMessage() == "unhandled_exception"
    ]
    assert len(records) == 1
    assert getattr(records[0], "request_id", None) == request_id
