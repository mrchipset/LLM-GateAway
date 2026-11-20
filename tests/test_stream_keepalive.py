from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast
from uuid import uuid4

from llm_gateway.api.inference import _stream_sse
from llm_gateway.providers.base import ProviderName
from llm_gateway.schemas.chat import ChatCompletionChunk
from llm_gateway.services.chat import ChatStream
from llm_gateway.services.usage import UsageContext


def _chunk(delta: dict[str, object], finish: str | None = None) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        {
            "id": "c1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "m",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
    )


async def _collect(*, keepalive_seconds: float, delay: float) -> str:
    async def upstream() -> AsyncGenerator[ChatCompletionChunk, None]:
        await asyncio.sleep(delay)
        yield _chunk({"content": "hello"})
        yield _chunk({}, finish="stop")

    stream = ChatStream(
        first_chunk=_chunk({"role": "assistant", "content": ""}),
        model_id="m",
        provider=ProviderName.OPENAI,
        client_wants_usage=False,
        usage=None,
        upstream=upstream(),
    )
    context = UsageContext(
        request_id="test",
        tenant_id=uuid4(),
        api_key_id=uuid4(),
        model_id="m",
        provider=ProviderName.OPENAI,
    )
    frames = [
        frame
        async for frame in _stream_sse(
            stream,
            recorder=cast(Any, None),
            context=context,
            keepalive_seconds=keepalive_seconds,
        )
    ]
    return b"".join(frames).decode()


async def test_keepalive_comment_is_emitted_while_waiting_for_the_next_chunk() -> None:
    text = await _collect(keepalive_seconds=0.01, delay=0.05)

    assert ": keepalive\n\n" in text
    assert '"content":"hello"' in text
    assert text.rstrip().endswith("data: [DONE]")


async def test_keepalive_is_disabled_when_zero() -> None:
    text = await _collect(keepalive_seconds=0.0, delay=0.05)

    assert ": keepalive" not in text
    assert '"content":"hello"' in text
