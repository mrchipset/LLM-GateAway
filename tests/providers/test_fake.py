from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from llm_gateway.clock import Clock
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.schemas.chat import ChatCompletionRequest, ChatMessage

FIXED_NOW = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
UPSTREAM_MODEL = "gpt-upstream"


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def make_provider() -> FakeProvider:
    return FakeProvider(clock=cast(Clock, FixedClock(FIXED_NOW)))


def make_request(
    *,
    messages: list[ChatMessage] | None = None,
    stream_options: dict[str, object] | None = None,
) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="public-model",
        messages=messages
        if messages is not None
        else [
            ChatMessage(role="system", content="you are here"),
            ChatMessage(role="user", content="what is two plus two"),
            ChatMessage(role="assistant", content="four"),
            ChatMessage(role="user", content="and three plus three"),
        ],
        stream_options=stream_options,
    )


async def test_complete_is_deterministic_for_same_messages() -> None:
    provider = make_provider()
    request = make_request()

    first = await provider.complete(upstream_model=UPSTREAM_MODEL, request=request)
    second = await provider.complete(upstream_model=UPSTREAM_MODEL, request=request)

    assert first == second


async def test_complete_uses_last_user_message_and_fixed_clock() -> None:
    provider = make_provider()

    response = await provider.complete(upstream_model=UPSTREAM_MODEL, request=make_request())

    assert response.model == UPSTREAM_MODEL
    assert response.created == int(FIXED_NOW.timestamp())
    assert response.id.startswith("chatcmpl-fake-")
    assert len(response.id) == len("chatcmpl-fake-") + 24
    assert len(response.choices) == 1
    assert response.choices[0].index == 0
    assert response.choices[0].finish_reason == "stop"
    assert response.choices[0].message.role == "assistant"
    assert response.choices[0].message.content == "fake completion for: and three plus three"


async def test_complete_id_changes_with_upstream_model() -> None:
    provider = make_provider()
    request = make_request()

    first = await provider.complete(upstream_model="model-a", request=request)
    second = await provider.complete(upstream_model="model-b", request=request)

    assert first.id != second.id


async def test_complete_joins_text_parts_and_counts_words() -> None:
    provider = make_provider()
    request = make_request(
        messages=[
            ChatMessage(role="system", content="be brief"),
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": "hello"},
                    {"type": "image_url", "image_url": {"url": "ignored"}},
                    {"type": "text", "text": " world"},
                ],
            ),
        ]
    )

    response = await provider.complete(upstream_model=UPSTREAM_MODEL, request=request)

    assert response.choices[0].message.content == "fake completion for: hello world"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 4
    assert response.usage.completion_tokens == 5
    assert response.usage.total_tokens == 9


async def test_complete_without_user_message_uses_empty_text() -> None:
    provider = make_provider()
    request = make_request(messages=[ChatMessage(role="system", content="only system")])

    response = await provider.complete(upstream_model=UPSTREAM_MODEL, request=request)

    assert response.choices[0].message.content == "fake completion for: "
    assert response.usage is not None
    assert response.usage.prompt_tokens == 2
    assert response.usage.completion_tokens == 3


async def test_stream_sequence_without_usage_option() -> None:
    provider = make_provider()
    request = make_request()

    chunks = [
        chunk async for chunk in provider.stream(upstream_model=UPSTREAM_MODEL, request=request)
    ]

    assert chunks[0].choices[0].delta.role == "assistant"
    assert chunks[0].choices[0].delta.content == ""
    assert chunks[0].choices[0].finish_reason is None

    token_chunks = chunks[1:-1]
    assert [chunk.choices[0].delta.content for chunk in token_chunks] == [
        "fake ",
        "completion ",
        "for: ",
        "and ",
        "three ",
        "plus ",
        "three",
    ]
    assert "".join(cast(str, chunk.choices[0].delta.content) for chunk in token_chunks) == (
        "fake completion for: and three plus three"
    )

    finish = chunks[-1]
    assert finish.choices[0].finish_reason == "stop"
    assert finish.choices[0].delta.role is None
    assert finish.choices[0].delta.content is None
    assert finish.usage is None
    assert {chunk.id for chunk in chunks} == {chunks[0].id}


async def test_stream_emits_usage_chunk_only_when_requested() -> None:
    provider = make_provider()
    request = make_request(stream_options={"include_usage": True})

    chunks = [
        chunk async for chunk in provider.stream(upstream_model=UPSTREAM_MODEL, request=request)
    ]

    usage_chunk = chunks[-1]
    assert usage_chunk.choices == []
    assert usage_chunk.usage is not None
    assert usage_chunk.usage.completion_tokens == 7
    assert chunks[-2].choices[0].finish_reason == "stop"


async def test_stream_empty_text_still_has_finish_chunk() -> None:
    provider = make_provider()
    request = make_request(messages=[ChatMessage(role="system", content="only system")])

    chunks = [
        chunk async for chunk in provider.stream(upstream_model=UPSTREAM_MODEL, request=request)
    ]

    assert chunks[0].choices[0].delta.role == "assistant"
    assert [chunk.choices[0].delta.content for chunk in chunks[1:-1]] == [
        "fake ",
        "completion ",
        "for:",
    ]
    assert chunks[-1].choices[0].finish_reason == "stop"


async def test_aclose_is_idempotent() -> None:
    provider = make_provider()

    await provider.aclose()
    await provider.aclose()
