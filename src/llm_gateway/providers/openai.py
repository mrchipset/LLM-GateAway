from __future__ import annotations

import codecs
import json
from collections.abc import AsyncGenerator, AsyncIterator
from random import Random
from typing import cast

import httpx
from pydantic import ValidationError

from llm_gateway.providers.base import (
    ProviderConnectionError,
    ProviderError,
    ProviderName,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from llm_gateway.providers.retry import RetryPolicy, Sleeper, asyncio_sleep
from llm_gateway.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)

_MAX_ERROR_MESSAGE = 300


def _truncate(message: str) -> str:
    return message[:_MAX_ERROR_MESSAGE]


def _error_message_from_body(body: object, status_code: int) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message:
                return _truncate(message)
    return f"upstream returned status {status_code}"


def _error_message_from_frame(payload: dict[str, object]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return _truncate(message)
    if isinstance(error, str) and error:
        return _truncate(error)
    return "Upstream provider returned an error"


def _parse_sse_line(line: str) -> str | None:
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    value = line[len("data:") :]
    if value.startswith(" "):
        value = value[1:]
    return value


class OpenAIProvider:
    name = ProviderName.OPENAI

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: httpx.Timeout,
        retry_policy: RetryPolicy,
        client: httpx.AsyncClient | None = None,
        sleeper: Sleeper = asyncio_sleep,
        rng: Random | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._retry_policy = retry_policy
        self._sleeper = sleeper
        self._rng = rng if rng is not None else Random()  # noqa: S311 - jitter, not security
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient(timeout=timeout)
        self._closed = False

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _post(self, payload: dict[str, object]) -> httpx.Response:
        try:
            return await self._client.post(
                self._endpoint,
                json=payload,
                headers=self._headers,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError() from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError() from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError() from exc

    async def _send_stream(self, payload: dict[str, object]) -> httpx.Response:
        try:
            request = self._client.build_request(
                "POST",
                self._endpoint,
                json=payload,
                headers=self._headers,
            )
            return await self._client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError() from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError() from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError() from exc

    async def _sleep_before_retry(self, attempt: int) -> None:
        await self._sleeper(self._retry_policy.delay_for_attempt(attempt, self._rng))

    def _upstream_error(self, response: httpx.Response) -> ProviderUpstreamError:
        try:
            body = response.json()
        except ValueError:
            body = None
        return ProviderUpstreamError(
            status_code=response.status_code,
            message=_error_message_from_body(body, response.status_code),
        )

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        payload: dict[str, object] = {
            "model": upstream_model,
            **request.as_upstream_payload(stream=False),
        }
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._post(payload)
                if not 200 <= response.status_code < 300:
                    raise self._upstream_error(response)
                return self._parse_completion(response)
            except ProviderError as exc:
                if not exc.retryable or attempt >= self._retry_policy.max_attempts:
                    raise
                await self._sleep_before_retry(attempt)

    def _parse_completion(self, response: httpx.Response) -> ChatCompletionResponse:
        try:
            body = response.json()
            return ChatCompletionResponse.model_validate(body)
        except (ValueError, ValidationError) as exc:
            raise ProviderResponseError() from exc

    async def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        payload: dict[str, object] = {
            "model": upstream_model,
            **request.as_upstream_payload(stream=True),
        }
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._send_stream(payload)
                if not 200 <= response.status_code < 300:
                    await response.aread()
                    error = self._upstream_error(response)
                    await response.aclose()
                    raise error
                break
            except ProviderError as exc:
                if not exc.retryable or attempt >= self._retry_policy.max_attempts:
                    raise
                await self._sleep_before_retry(attempt)

        seen_done = False
        seen_finish = False
        try:
            async for data in self._iter_sse_data(response):
                if data == "[DONE]":
                    seen_done = True
                    break
                chunk = self._parse_chunk(data)
                if any(choice.finish_reason is not None for choice in chunk.choices):
                    seen_finish = True
                yield chunk
            if not seen_done and not seen_finish:
                raise ProviderResponseError("Upstream stream ended before completion")
        finally:
            await response.aclose()

    async def _iter_sse_data(self, response: httpx.Response) -> AsyncIterator[str]:
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        buffer = ""
        async for raw in response.aiter_bytes():
            buffer += self._decode(decoder, raw)
            while True:
                newline = buffer.find("\n")
                if newline < 0:
                    break
                line = buffer[:newline]
                buffer = buffer[newline + 1 :]
                data = _parse_sse_line(line.rstrip("\r"))
                if data is not None:
                    yield data

        buffer += self._decode(decoder, b"", final=True)
        data = _parse_sse_line(buffer.rstrip("\r"))
        if data is not None:
            yield data

    @staticmethod
    def _decode(decoder: codecs.IncrementalDecoder, raw: bytes, *, final: bool = False) -> str:
        try:
            return decoder.decode(raw, final)
        except UnicodeDecodeError as exc:
            raise ProviderResponseError() from exc

    @staticmethod
    def _parse_chunk(data: str) -> ChatCompletionChunk:
        try:
            payload = json.loads(data)
        except ValueError as exc:
            raise ProviderResponseError() from exc
        if not isinstance(payload, dict):
            raise ProviderResponseError()
        if "error" in payload:
            raise ProviderUpstreamError(
                status_code=None,
                message=_error_message_from_frame(cast(dict[str, object], payload)),
            )
        try:
            return ChatCompletionChunk.model_validate(payload)
        except ValidationError as exc:
            raise ProviderResponseError() from exc

    async def aclose(self) -> None:
        if not self._owns_client or self._closed:
            return
        self._closed = True
        await self._client.aclose()
