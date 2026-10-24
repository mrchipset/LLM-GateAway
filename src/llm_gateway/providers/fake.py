from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncGenerator

from llm_gateway.clock import Clock
from llm_gateway.providers.base import ProviderName
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


def _text_of_content(content: str | list[dict[str, object]] | None) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return ""


def _message_text(message: ChatMessage) -> str:
    return _text_of_content(message.content)


def _word_count(text: str) -> int:
    return len(text.split())


class FakeProvider:
    name = ProviderName.FAKE

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    def _completion_id(self, upstream_model: str, request: ChatCompletionRequest) -> str:
        serialized = json.dumps(
            [message.model_dump(mode="json") for message in request.messages],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        digest = hashlib.sha256((upstream_model + serialized).encode("utf-8")).hexdigest()
        return f"chatcmpl-fake-{digest[:24]}"

    def _reply(self, request: ChatCompletionRequest) -> str:
        for message in reversed(request.messages):
            if message.role == "user":
                return f"fake completion for: {_message_text(message)}"
        return "fake completion for: "

    def _usage(self, request: ChatCompletionRequest, reply: str) -> Usage:
        prompt_tokens = sum(_word_count(_message_text(message)) for message in request.messages)
        completion_tokens = _word_count(reply)
        return Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    def _created(self) -> int:
        return int(self._clock.now().timestamp())

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        reply = self._reply(request)
        return ChatCompletionResponse(
            id=self._completion_id(upstream_model, request),
            created=self._created(),
            model=upstream_model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=reply),
                    finish_reason="stop",
                )
            ],
            usage=self._usage(request, reply),
        )

    async def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        completion_id = self._completion_id(upstream_model, request)
        reply = self._reply(request)
        created = self._created()

        yield ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=upstream_model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatDelta(role="assistant", content=""),
                    finish_reason=None,
                )
            ],
        )

        tokens = reply.split()
        for position, token in enumerate(tokens):
            is_last = position == len(tokens) - 1
            yield ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=upstream_model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatDelta(content=token + ("" if is_last else " ")),
                        finish_reason=None,
                    )
                ],
            )

        yield ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=upstream_model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatDelta(),
                    finish_reason="stop",
                )
            ],
        )

        stream_options = request.stream_options
        if isinstance(stream_options, dict) and stream_options.get("include_usage"):
            yield ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=upstream_model,
                choices=[],
                usage=self._usage(request, reply),
            )

    async def aclose(self) -> None:
        return None
