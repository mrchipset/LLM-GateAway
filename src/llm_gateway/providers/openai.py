from __future__ import annotations

import codecs
import json
from collections.abc import AsyncGenerator, AsyncIterator
from random import Random
from time import perf_counter
from typing import cast

import httpx
from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Tracer
from pydantic import ValidationError

from llm_gateway.metrics import current_metrics
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
from llm_gateway.telemetry import inject_trace_context, mark_span_error

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
    """Serves OpenAI and other OpenAI-compatible providers.

    DeepSeek and similar upstreams share the same wire protocol, so a different
    ``name`` and ``base_url`` are enough to target them without a new adapter.
    """

    name = ProviderName.OPENAI

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: httpx.Timeout,
        retry_policy: RetryPolicy,
        name: ProviderName = ProviderName.OPENAI,
        client: httpx.AsyncClient | None = None,
        sleeper: Sleeper = asyncio_sleep,
        rng: Random | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self.name = name
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._retry_policy = retry_policy
        self._sleeper = sleeper
        self._rng = rng if rng is not None else Random()  # noqa: S311 - jitter, not security
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient(timeout=timeout)
        self._tracer = tracer if tracer is not None else trace.get_tracer(__name__)
        self._closed = False

    def _request_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        # Must be called inside the attempt span so the outgoing ``traceparent``
        # carries this attempt's id, not the inbound one.
        inject_trace_context(headers)
        return headers

    def _start_attempt_span(
        self,
        *,
        model_id: str,
        upstream_model: str,
        attempt: int,
        stream: bool,
    ) -> Span:
        return self._tracer.start_span(
            f"{self.name.value} chat",
            kind=SpanKind.CLIENT,
            attributes={
                "llm.provider": self.name.value,
                "llm.model_id": model_id,
                "llm.upstream_model": upstream_model,
                "llm.attempt": attempt,
                "llm.stream": stream,
            },
        )

    def _mark_attempt_failed(self, span: Span, exc: ProviderError) -> None:
        span.set_attribute("llm.retryable", exc.retryable)
        mark_span_error(span, status_code=getattr(exc, "status_code", None))

    def _record_attempt(self, *, model_id: str, status: str, started: float) -> None:
        instruments = current_metrics()
        attributes = {"provider": self.name.value, "model": model_id}
        instruments.upstream_requests.add(1, {**attributes, "status": status})
        instruments.upstream_duration.record(perf_counter() - started, attributes)

    @staticmethod
    def _status_label(exc: ProviderError) -> str:
        status_code = getattr(exc, "status_code", None)
        return str(status_code) if status_code is not None else "error"

    async def _post(self, payload: dict[str, object], *, headers: dict[str, str]) -> httpx.Response:
        try:
            return await self._client.post(
                self._endpoint,
                json=payload,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError() from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError() from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError() from exc

    async def _send_stream(
        self, payload: dict[str, object], *, headers: dict[str, str]
    ) -> httpx.Response:
        try:
            request = self._client.build_request(
                "POST",
                self._endpoint,
                json=payload,
                headers=headers,
            )
            return await self._client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError() from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError() from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError() from exc

    async def _drain_stream_error(self, response: httpx.Response) -> None:
        try:
            await response.aread()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError() from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError() from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError() from exc
        finally:
            await response.aclose()

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
            span = self._start_attempt_span(
                model_id=request.model,
                upstream_model=upstream_model,
                attempt=attempt,
                stream=False,
            )
            started = perf_counter()
            try:
                with trace.use_span(span, end_on_exit=False):
                    response = await self._post(payload, headers=self._request_headers())
                    if not 200 <= response.status_code < 300:
                        raise self._upstream_error(response)
                    span.set_attribute("http.response.status_code", response.status_code)
                    result = self._parse_completion(response)
                    span.set_attribute(
                        "llm.duration_ms",
                        round((perf_counter() - started) * 1000, 2),
                    )
                    if result.usage is not None:
                        span.set_attribute("llm.total_tokens", result.usage.total_tokens)
                    self._record_attempt(
                        model_id=request.model,
                        status=str(response.status_code),
                        started=started,
                    )
                    return result
            except ProviderError as exc:
                self._mark_attempt_failed(span, exc)
                self._record_attempt(
                    model_id=request.model,
                    status=self._status_label(exc),
                    started=started,
                )
                if not exc.retryable or attempt >= self._retry_policy.max_attempts:
                    raise
                await self._sleep_before_retry(attempt)
            finally:
                span.end()

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
            span = self._start_attempt_span(
                model_id=request.model,
                upstream_model=upstream_model,
                attempt=attempt,
                stream=True,
            )
            started = perf_counter()
            try:
                with trace.use_span(span, end_on_exit=False):
                    response = await self._send_stream(payload, headers=self._request_headers())
                if not 200 <= response.status_code < 300:
                    await self._drain_stream_error(response)
                    raise self._upstream_error(response)
                span.set_attribute("http.response.status_code", response.status_code)
                break
            except ProviderError as exc:
                self._mark_attempt_failed(span, exc)
                span.end()
                self._record_attempt(
                    model_id=request.model,
                    status=self._status_label(exc),
                    started=started,
                )
                if not exc.retryable or attempt >= self._retry_policy.max_attempts:
                    raise
                await self._sleep_before_retry(attempt)

        seen_done = False
        seen_finish = False
        first_chunk = True
        completed = False
        outcome = "cancelled"
        try:
            async for data in self._iter_sse_data(response):
                if data == "[DONE]":
                    seen_done = True
                    completed = True
                    break
                chunk = self._parse_chunk(data)
                if first_chunk:
                    ttft = perf_counter() - started
                    span.set_attribute("llm.ttft_ms", round(ttft * 1000, 2))
                    current_metrics().upstream_ttft.record(
                        ttft,
                        {"provider": self.name.value, "model": request.model},
                    )
                    first_chunk = False
                if any(choice.finish_reason is not None for choice in chunk.choices):
                    seen_finish = True
                yield chunk
            if not seen_done and not seen_finish:
                raise ProviderResponseError("Upstream stream ended before completion")
            completed = True
            outcome = "ok"
        except ProviderError as exc:
            outcome = self._status_label(exc)
            self._mark_attempt_failed(span, exc)
            raise
        finally:
            await response.aclose()
            span.set_attribute("llm.stream_completed", completed)
            span.end()
            self._record_attempt(
                model_id=request.model,
                status=outcome,
                started=started,
            )

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
