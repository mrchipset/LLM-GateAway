from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """One OpenAI-style chat message.

    `extra="allow"` keeps forward compatibility with upstream fields the gateway
    does not model yet (for example `refusal` or provider-specific annotations).
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[dict[str, object]] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, object]] | None = None


class ChatCompletionRequest(BaseModel):
    """Inference request accepted on `/v1/chat/completions`.

    Unknown fields are forwarded upstream instead of rejected, because OpenAI
    clients routinely send optional parameters the gateway does not model. The
    gateway-owned `model` field is the public model name and is never forwarded
    as-is; providers receive the resolved `upstream_model`.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    stop: str | list[str] | None = None
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    n: int | None = Field(default=None, ge=1, le=8)
    user: str | None = None
    seed: int | None = None
    response_format: dict[str, object] | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: str | dict[str, object] | None = None
    stream_options: dict[str, object] | None = None

    def as_upstream_payload(self, *, stream: bool) -> dict[str, object]:
        """Return the provider payload without gateway routing fields."""
        payload = self.model_dump(exclude_none=True, mode="json")
        payload.pop("model", None)
        payload["stream"] = stream
        return payload


class Usage(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ChatCompletionChoice(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    index: int = Field(ge=0)
    message: ChatMessage
    finish_reason: str | None = None


class ChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice] = Field(min_length=1)
    usage: Usage | None = None
    system_fingerprint: str | None = None


class ChatDelta(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    role: Literal["system", "developer", "user", "assistant", "tool"] | None = None
    content: str | None = None
    tool_calls: list[dict[str, object]] | None = None


class ChatCompletionChunkChoice(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    index: int = Field(ge=0)
    delta: ChatDelta = Field(default_factory=ChatDelta)
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChunkChoice] = Field(default_factory=list)
    usage: Usage | None = None
    system_fingerprint: str | None = None


class ModelSummary(BaseModel):
    """Entry returned by `GET /v1/models`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    object: Literal["model"] = "model"
    created: int
    owned_by: str


class ModelListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    object: Literal["list"] = "list"
    data: list[ModelSummary]
