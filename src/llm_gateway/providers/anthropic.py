"""Anthropic Messages adapter.

The gateway's internal contract is OpenAI-compatible, while Anthropic exposes a
different wire format (``/v1/messages``, content blocks, typed SSE events). This
module keeps that difference inside the adapter boundary: requests are translated
into an explicit Messages payload and responses/events are translated back into
``ChatCompletionResponse``/``ChatCompletionChunk``.
"""

from __future__ import annotations

import asyncio
import codecs
import json
from collections.abc import AsyncGenerator, AsyncIterator
from random import Random
from time import perf_counter, time
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
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatDelta,
    ChatMessage,
    Usage,
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


def _as_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return None


def _as_list(value: object) -> list[object] | None:
    if isinstance(value, list):
        return cast(list[object], value)
    return None


def _non_negative_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _content_text(content: str | list[dict[str, object]] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for part in content:
        if part.get("type") != "text":
            raise ProviderError("Anthropic adapter supports only text content parts")
        text = part.get("text")
        if not isinstance(text, str):
            raise ProviderError("OpenAI text content part is missing 'text'")
        parts.append(text)
    return "".join(parts)


def _text_blocks(content: str | list[dict[str, object]] | None) -> list[dict[str, object]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    blocks: list[dict[str, object]] = []
    for part in content:
        if part.get("type") != "text":
            raise ProviderError("Anthropic adapter supports only text content parts")
        text = part.get("text")
        if not isinstance(text, str):
            raise ProviderError("OpenAI text content part is missing 'text'")
        blocks.append({"type": "text", "text": text})
    return blocks


def _user_content(content: str | list[dict[str, object]] | None) -> str | list[dict[str, object]]:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return _text_blocks(content)


def _tool_use_block(call: dict[str, object]) -> dict[str, object]:
    call_id = call.get("id")
    function = _as_dict(call.get("function"))
    if not isinstance(call_id, str) or not call_id or function is None:
        raise ProviderError("malformed assistant tool_call")
    name = function.get("name")
    if not isinstance(name, str) or not name:
        raise ProviderError("assistant tool_call is missing a function name")
    arguments = function.get("arguments")
    parsed: object = {}
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
        except ValueError as exc:
            raise ProviderError("assistant tool_call arguments are not valid JSON") from exc
    input_value = _as_dict(parsed)
    if input_value is None:
        raise ProviderError("assistant tool_call arguments must be a JSON object")
    return {"type": "tool_use", "id": call_id, "name": name, "input": input_value}


def _assistant_content(message: ChatMessage) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    if isinstance(message.content, str):
        if message.content:
            blocks.append({"type": "text", "text": message.content})
    else:
        blocks.extend(_text_blocks(message.content))
    for call in message.tool_calls or []:
        blocks.append(_tool_use_block(call))
    if not blocks:
        blocks.append({"type": "text", "text": ""})
    return blocks


def _tool_result_block(message: ChatMessage) -> dict[str, object]:
    tool_call_id = message.tool_call_id
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise ProviderError("tool message is missing tool_call_id")
    return {
        "type": "tool_result",
        "tool_use_id": tool_call_id,
        "content": _content_text(message.content),
    }


def _translate_messages(
    messages: list[ChatMessage],
) -> tuple[str | None, list[dict[str, object]]]:
    system_parts: list[str] = []
    translated: list[dict[str, object]] = []
    pending_tool_results: list[dict[str, object]] = []

    for message in messages:
        if message.role in ("system", "developer"):
            text = _content_text(message.content)
            if text:
                system_parts.append(text)
            continue

        if message.role == "tool":
            pending_tool_results.append(_tool_result_block(message))
            continue

        # Consecutive tool results form a single user turn.
        if pending_tool_results:
            translated.append({"role": "user", "content": list(pending_tool_results)})
            pending_tool_results.clear()

        if message.role == "assistant":
            translated.append({"role": "assistant", "content": _assistant_content(message)})
        else:
            translated.append({"role": "user", "content": _user_content(message.content)})

    if pending_tool_results:
        translated.append({"role": "user", "content": pending_tool_results})

    system = "\n\n".join(system_parts) if system_parts else None
    return system, translated


def _translate_tools(tools: list[dict[str, object]] | None) -> list[dict[str, object]] | None:
    if not tools:
        return None
    translated: list[dict[str, object]] = []
    for tool in tools:
        if tool.get("type") != "function":
            raise ProviderError("Anthropic adapter supports only function tools")
        function = _as_dict(tool.get("function"))
        if function is None:
            raise ProviderError("tool is missing a function definition")
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise ProviderError("tool is missing a function name")
        schema = _as_dict(function.get("parameters"))
        entry: dict[str, object] = {
            "name": name,
            "input_schema": schema if schema is not None else {"type": "object", "properties": {}},
        }
        description = function.get("description")
        if isinstance(description, str):
            entry["description"] = description
        translated.append(entry)
    return translated


def _translate_tool_choice(
    tool_choice: str | dict[str, object] | None,
    tools: list[dict[str, object]] | None,
) -> tuple[list[dict[str, object]] | None, dict[str, object] | None]:
    if tool_choice == "none":
        return None, None
    translated_tools = _translate_tools(tools)
    if tool_choice is None:
        return translated_tools, None
    if isinstance(tool_choice, str):
        if tool_choice == "auto":
            return translated_tools, {"type": "auto"}
        if tool_choice == "required":
            return translated_tools, {"type": "any"}
        raise ProviderError(f"unsupported tool_choice: {tool_choice}")
    function = _as_dict(tool_choice.get("function"))
    name = function.get("name") if function is not None else None
    if not isinstance(name, str) or not name:
        raise ProviderError("tool_choice is missing a function name")
    return translated_tools, {"type": "tool", "name": name}


def _stop_sequences(stop: str | list[str] | None) -> list[str] | None:
    if isinstance(stop, str):
        return [stop] if stop else None
    if isinstance(stop, list):
        return stop if stop else None
    return None


def _build_payload(
    *,
    upstream_model: str,
    request: ChatCompletionRequest,
    default_max_tokens: int,
    stream: bool,
) -> dict[str, object]:
    system, messages = _translate_messages(request.messages)
    tools, tool_choice = _translate_tool_choice(request.tool_choice, request.tools)

    max_tokens = request.max_tokens
    if max_tokens is None:
        max_tokens = request.max_completion_tokens
    if max_tokens is None:
        max_tokens = default_max_tokens

    payload: dict[str, object] = {
        "model": upstream_model,
        "max_tokens": max_tokens,
        "messages": messages,
        "stream": stream,
    }
    if system is not None:
        payload["system"] = system
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    stop_sequences = _stop_sequences(request.stop)
    if stop_sequences is not None:
        payload["stop_sequences"] = stop_sequences
    if tools is not None:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    return payload


def _map_stop_reason(stop_reason: object) -> str | None:
    if stop_reason == "end_turn":
        return "stop"
    if stop_reason == "max_tokens":
        return "length"
    if stop_reason == "tool_use":
        return "tool_calls"
    if stop_reason == "stop_sequence":
        return "stop"
    return None


def _build_usage(*, prompt_tokens: int, completion_tokens: int, cached_tokens: int | None) -> Usage:
    data: dict[str, object] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    if cached_tokens is not None:
        data["prompt_tokens_details"] = {"cached_tokens": cached_tokens}
    return Usage.model_validate(data)


def _usage_from_body(usage: dict[str, object] | None) -> Usage | None:
    if usage is None:
        return None
    return _build_usage(
        prompt_tokens=_non_negative_int(usage.get("input_tokens")),
        completion_tokens=_non_negative_int(usage.get("output_tokens")),
        cached_tokens=_optional_non_negative_int(usage.get("cache_read_input_tokens")),
    )


def _translate_tool_use_block(block: dict[str, object]) -> dict[str, object]:
    call_id = block.get("id")
    name = block.get("name")
    if not isinstance(call_id, str) or not isinstance(name, str):
        raise ProviderResponseError("upstream tool_use block is missing id or name")
    tool_input = _as_dict(block.get("input"))
    if tool_input is None:
        raise ProviderResponseError("upstream tool_use block has a non-object input")
    arguments = json.dumps(tool_input, separators=(",", ":"), ensure_ascii=False)
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _translate_response(body: dict[str, object], *, model: str) -> ChatCompletionResponse:
    completion_id = body.get("id")
    if not isinstance(completion_id, str) or not completion_id:
        raise ProviderResponseError("upstream message is missing an id")

    content = _as_list(body.get("content"))
    if content is None:
        raise ProviderResponseError("upstream message is missing content")

    text_parts: list[str] = []
    tool_calls: list[dict[str, object]] = []
    for raw_block in content:
        block = _as_dict(raw_block)
        if block is None:
            raise ProviderResponseError("upstream content block is not an object")
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise ProviderResponseError("upstream text block is missing text")
            text_parts.append(text)
        elif block_type == "tool_use":
            tool_calls.append(_translate_tool_use_block(block))
        else:
            raise ProviderResponseError(f"unsupported upstream content block: {block_type}")

    text = "".join(text_parts)
    usage = _usage_from_body(_as_dict(body.get("usage")))
    message = ChatMessage(
        role="assistant",
        content=(text or None) if tool_calls else text,
        tool_calls=tool_calls or None,
    )
    return ChatCompletionResponse(
        id=completion_id,
        created=int(time()),
        model=model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=message,
                finish_reason=_map_stop_reason(body.get("stop_reason")),
            )
        ],
        usage=usage,
    )


class _StreamTranslator:
    """Turns Anthropic SSE events into OpenAI chunks, one event at a time."""

    def __init__(self, *, model: str) -> None:
        self.model = model
        self.created = int(time())
        self.completion_id = ""
        self.stop_reason: object = None
        self.seen_message_start = False
        self.completed = False
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cached_tokens: int | None = None
        self._tool_call_indices: dict[int, int] = {}
        self._next_tool_index = 0

    def _chunk(
        self,
        *,
        content: str | None = None,
        tool_calls: list[dict[str, object]] | None = None,
        finish_reason: str | None = None,
        usage: Usage | None = None,
    ) -> ChatCompletionChunk:
        return ChatCompletionChunk(
            id=self.completion_id or "msg_stream",
            created=self.created,
            model=self.model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatDelta(content=content, tool_calls=tool_calls),
                    finish_reason=finish_reason,
                )
            ],
            usage=usage,
        )

    def usage(self) -> Usage | None:
        if not self.seen_message_start:
            return None
        return _build_usage(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            cached_tokens=self.cached_tokens,
        )

    def handle(self, event: str | None, payload: dict[str, object]) -> ChatCompletionChunk | None:
        event_type = event if event is not None else payload.get("type")
        if event_type == "message_start":
            self._on_message_start(payload)
            return None
        if event_type == "content_block_start":
            return self._on_content_block_start(payload)
        if event_type == "content_block_delta":
            return self._on_content_block_delta(payload)
        if event_type == "content_block_stop":
            return None
        if event_type == "message_delta":
            self._on_message_delta(payload)
            return None
        if event_type == "message_stop":
            self.completed = True
            return self._chunk(finish_reason=_map_stop_reason(self.stop_reason), usage=self.usage())
        if event_type in ("ping", None):
            return None
        if event_type == "error":
            raise ProviderUpstreamError(
                status_code=None,
                message=_error_message_from_frame(payload),
            )
        raise ProviderResponseError(f"unsupported Anthropic stream event: {event_type}")

    def _on_message_start(self, payload: dict[str, object]) -> None:
        message = _as_dict(payload.get("message"))
        if message is None:
            raise ProviderResponseError("message_start is missing the message payload")
        completion_id = message.get("id")
        if isinstance(completion_id, str) and completion_id:
            self.completion_id = completion_id
        usage = _as_dict(message.get("usage"))
        if usage is not None:
            self.prompt_tokens = _non_negative_int(usage.get("input_tokens"))
            self.cached_tokens = _optional_non_negative_int(usage.get("cache_read_input_tokens"))
        self.seen_message_start = True

    def _on_content_block_start(self, payload: dict[str, object]) -> ChatCompletionChunk | None:
        if not self.seen_message_start:
            raise ProviderResponseError("content block started before message_start")
        block = _as_dict(payload.get("content_block"))
        if block is None:
            raise ProviderResponseError("content_block_start is missing content_block")
        if block.get("type") != "tool_use":
            return None

        block_index = _non_negative_int(payload.get("index"))
        tool_index = self._next_tool_index
        self._next_tool_index += 1
        self._tool_call_indices[block_index] = tool_index

        call_id = block.get("id")
        name = block.get("name")
        if not isinstance(call_id, str) or not isinstance(name, str):
            raise ProviderResponseError("upstream tool_use block is missing id or name")
        return self._chunk(
            tool_calls=[
                {
                    "index": tool_index,
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": ""},
                }
            ]
        )

    def _on_content_block_delta(self, payload: dict[str, object]) -> ChatCompletionChunk | None:
        if not self.seen_message_start:
            raise ProviderResponseError("content delta arrived before message_start")
        delta = _as_dict(payload.get("delta"))
        if delta is None:
            raise ProviderResponseError("content_block_delta is missing delta")
        delta_type = delta.get("type")
        if delta_type == "text_delta":
            text = delta.get("text")
            if not isinstance(text, str):
                raise ProviderResponseError("text_delta is missing text")
            return self._chunk(content=text)
        if delta_type == "input_json_delta":
            partial = delta.get("partial_json")
            if not isinstance(partial, str):
                raise ProviderResponseError("input_json_delta is missing partial_json")
            block_index = _non_negative_int(payload.get("index"))
            tool_index = self._tool_call_indices.get(block_index)
            if tool_index is None:
                raise ProviderResponseError("input_json_delta for an unknown content block")
            return self._chunk(
                tool_calls=[
                    {"index": tool_index, "function": {"arguments": partial}},
                ]
            )
        raise ProviderResponseError(f"unsupported content block delta: {delta_type}")

    def _on_message_delta(self, payload: dict[str, object]) -> None:
        delta = _as_dict(payload.get("delta"))
        if delta is not None and "stop_reason" in delta:
            self.stop_reason = delta.get("stop_reason")
        usage = _as_dict(payload.get("usage"))
        if usage is not None:
            self.completion_tokens = _non_negative_int(usage.get("output_tokens"))


def _parse_event(event: str | None, data: str) -> tuple[str | None, dict[str, object]]:
    try:
        payload = json.loads(data)
    except ValueError as exc:
        raise ProviderResponseError() from exc
    body = _as_dict(payload)
    if body is None:
        raise ProviderResponseError()
    return event, body


def _parse_sse_field(line: str, field: str) -> str | None:
    prefix = f"{field}:"
    if not line.startswith(prefix):
        return None
    value = line[len(prefix) :]
    if value.startswith(" "):
        value = value[1:]
    return value


class AnthropicProvider:
    """Anthropic Messages adapter exposed as an OpenAI-compatible provider."""

    name = ProviderName.ANTHROPIC

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        version: str = "2023-06-01",
        default_max_tokens: int = 1024,
        timeout: httpx.Timeout,
        retry_policy: RetryPolicy,
        client: httpx.AsyncClient | None = None,
        sleeper: Sleeper = asyncio_sleep,
        tracer: Tracer | None = None,
        stream_idle_timeout_seconds: float = 0.0,
    ) -> None:
        self._api_key = api_key
        self._version = version
        self._default_max_tokens = default_max_tokens
        self._stream_idle_timeout_seconds = stream_idle_timeout_seconds
        self._endpoint = f"{base_url.rstrip('/')}/v1/messages"
        self._retry_policy = retry_policy
        self._sleeper = sleeper
        self._rng = Random()  # noqa: S311 - jitter, not security
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient(timeout=timeout)
        self._tracer = tracer if tracer is not None else trace.get_tracer(__name__)
        self._closed = False

    def _request_headers(self) -> dict[str, str]:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self._version,
            "content-type": "application/json",
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
            body: object = response.json()
        except ValueError:
            body = None
        return ProviderUpstreamError(
            status_code=response.status_code,
            message=_error_message_from_body(body, response.status_code),
        )

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        payload = _build_payload(
            upstream_model=upstream_model,
            request=request,
            default_max_tokens=self._default_max_tokens,
            stream=False,
        )
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
                    result = self._parse_completion(response, model=request.model)
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

    @staticmethod
    def _parse_completion(response: httpx.Response, *, model: str) -> ChatCompletionResponse:
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise ProviderResponseError() from exc
        body = _as_dict(payload)
        if body is None:
            raise ProviderResponseError()
        try:
            return _translate_response(body, model=model)
        except ValidationError as exc:
            raise ProviderResponseError() from exc

    async def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        payload = _build_payload(
            upstream_model=upstream_model,
            request=request,
            default_max_tokens=self._default_max_tokens,
            stream=True,
        )
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

        translator = _StreamTranslator(model=request.model)
        first_chunk = True
        outcome = "cancelled"
        try:
            async for event, data in self._iter_sse_events(response):
                _, body = _parse_event(event, data)
                chunk = translator.handle(event, body)
                if chunk is None:
                    continue
                if first_chunk:
                    ttft = perf_counter() - started
                    span.set_attribute("llm.ttft_ms", round(ttft * 1000, 2))
                    current_metrics().upstream_ttft.record(
                        ttft,
                        {"provider": self.name.value, "model": request.model},
                    )
                    first_chunk = False
                yield chunk
            if not translator.completed:
                raise ProviderResponseError("Upstream stream ended before completion")
            outcome = "ok"
        except ProviderError as exc:
            outcome = self._status_label(exc)
            self._mark_attempt_failed(span, exc)
            raise
        finally:
            await response.aclose()
            span.set_attribute("llm.stream_completed", translator.completed)
            span.end()
            self._record_attempt(
                model_id=request.model,
                status=outcome,
                started=started,
            )

    async def _iter_sse_events(
        self, response: httpx.Response
    ) -> AsyncIterator[tuple[str | None, str]]:
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        buffer = ""
        event_name: str | None = None
        data_lines: list[str] = []
        byte_iterator = response.aiter_bytes().__aiter__()

        while True:
            raw = await self._next_stream_bytes(byte_iterator)
            if raw is None:
                break
            buffer += self._decode(decoder, raw)
            while True:
                newline = buffer.find("\n")
                if newline < 0:
                    break
                line = buffer[:newline].rstrip("\r")
                buffer = buffer[newline + 1 :]
                if not line:
                    if data_lines:
                        yield event_name, "\n".join(data_lines)
                    event_name = None
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                value = _parse_sse_field(line, "event")
                if value is not None:
                    event_name = value
                    continue
                value = _parse_sse_field(line, "data")
                if value is not None:
                    data_lines.append(value)

        buffer += self._decode(decoder, b"", final=True)
        trailing = buffer.rstrip("\r")
        if trailing:
            value = _parse_sse_field(trailing, "data")
            if value is not None:
                data_lines.append(value)
        if data_lines:
            yield event_name, "\n".join(data_lines)

    async def _next_stream_bytes(self, iterator: AsyncIterator[bytes]) -> bytes | None:
        """Return the next chunk, ``None`` at end of stream, or raise on idle.

        The timeout bounds the wait for the next bytes, not the total stream
        duration, so a slow but still-producing upstream is not interrupted.
        """
        if self._stream_idle_timeout_seconds == 0:
            try:
                return await iterator.__anext__()
            except StopAsyncIteration:
                return None

        try:
            async with asyncio.timeout(self._stream_idle_timeout_seconds):
                return await iterator.__anext__()
        except StopAsyncIteration:
            return None
        except TimeoutError as exc:
            timeout = self._stream_idle_timeout_seconds
            raise ProviderTimeoutError(f"Upstream stream idle for {timeout:g}s") from exc

    @staticmethod
    def _decode(decoder: codecs.IncrementalDecoder, raw: bytes, *, final: bool = False) -> str:
        try:
            return decoder.decode(raw, final)
        except UnicodeDecodeError as exc:
            raise ProviderResponseError() from exc

    async def aclose(self) -> None:
        if not self._owns_client or self._closed:
            return
        self._closed = True
        await self._client.aclose()
