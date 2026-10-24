from __future__ import annotations

from collections.abc import AsyncGenerator
from enum import StrEnum
from typing import Protocol

from llm_gateway.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)


class ProviderName(StrEnum):
    OPENAI = "openai"
    FAKE = "fake"


class ProviderError(Exception):
    """Base class for provider failures that are safe to surface to clients."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


class ProviderTimeoutError(ProviderError):
    def __init__(self, message: str = "Upstream provider timed out") -> None:
        super().__init__(message, retryable=True)


class ProviderConnectionError(ProviderError):
    def __init__(self, message: str = "Could not connect to upstream provider") -> None:
        super().__init__(message, retryable=True)


class ProviderUpstreamError(ProviderError):
    """Non-success HTTP response from the provider, or an upstream error frame."""

    def __init__(self, *, status_code: int | None, message: str) -> None:
        retryable = status_code is not None and (status_code == 429 or status_code >= 500)
        super().__init__(message, retryable=retryable)
        self.status_code = status_code


class ProviderResponseError(ProviderError):
    """The provider returned a payload the gateway cannot interpret."""

    def __init__(self, message: str = "Upstream provider returned an invalid response") -> None:
        super().__init__(message, retryable=False)


class ProviderNotConfiguredError(Exception):
    def __init__(self, provider: ProviderName) -> None:
        super().__init__(f"provider '{provider.value}' is not configured")
        self.provider = provider


class ChatProvider(Protocol):
    name: ProviderName

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse: ...

    def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]: ...

    async def aclose(self) -> None: ...
