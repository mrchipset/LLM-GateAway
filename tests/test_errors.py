from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

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
    error = _error_body(response)
    assert error["type"] == "invalid_request_error"
    assert error["code"] == ApiErrorCode.METHOD_NOT_ALLOWED.value


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
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/upstream")
    def upstream() -> None:
        from fastapi import HTTPException

        raise HTTPException(status_code=status_code, detail="upstream secret detail")

    response = await _get(app, "/upstream")

    assert response.status_code == status_code
    error = _error_body(response)
    assert error["code"] == ApiErrorCode.INTERNAL_ERROR.value
    assert error["type"] == "server_error"
    assert "upstream secret detail" not in response.text
