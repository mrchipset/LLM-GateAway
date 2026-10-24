from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass

from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.logging import get_logger
from llm_gateway.providers.base import (
    ChatProvider,
    ProviderConnectionError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUpstreamError,
)
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from llm_gateway.storage.repositories import ModelConfig, ModelRepository

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    config: ModelConfig
    provider: ChatProvider


def _error(
    *,
    status_code: int,
    code: ApiErrorCode,
    message: str,
    error_type: str,
    param: str | None = None,
) -> ApiError:
    return ApiError(
        status_code=status_code,
        code=code,
        message=message,
        error_type=error_type,
        param=param,
    )


def map_provider_error(exc: ProviderError) -> ApiError:
    """Translate one provider failure into a stable client-facing error."""
    status_code = getattr(exc, "status_code", None)
    logger.warning(
        "provider_error",
        extra={
            "provider_error": type(exc).__name__,
            "status_code": status_code,
        },
    )

    if isinstance(exc, ProviderTimeoutError):
        return _error(
            status_code=504,
            code=ApiErrorCode.UPSTREAM_TIMEOUT,
            message="Upstream provider timed out",
            error_type="server_error",
        )

    if isinstance(exc, ProviderConnectionError):
        return _error(
            status_code=502,
            code=ApiErrorCode.UPSTREAM_UNAVAILABLE,
            message="Upstream provider is unavailable",
            error_type="server_error",
        )

    if isinstance(exc, ProviderResponseError):
        return _error(
            status_code=502,
            code=ApiErrorCode.UPSTREAM_INVALID_RESPONSE,
            message="Upstream provider returned an invalid response",
            error_type="server_error",
        )

    if isinstance(exc, ProviderUpstreamError):
        if exc.status_code is None:
            return _error(
                status_code=502,
                code=ApiErrorCode.UPSTREAM_UNAVAILABLE,
                message="Upstream provider returned an error",
                error_type="server_error",
            )
        if exc.status_code in (401, 403):
            return _error(
                status_code=502,
                code=ApiErrorCode.UPSTREAM_AUTH_FAILED,
                message="Upstream provider rejected the gateway credentials",
                error_type="server_error",
            )
        if exc.status_code == 429:
            return _error(
                status_code=429,
                code=ApiErrorCode.UPSTREAM_RATE_LIMITED,
                message="Upstream provider rate limit exceeded",
                error_type="rate_limit_error",
            )
        if exc.status_code >= 500:
            return _error(
                status_code=502,
                code=ApiErrorCode.UPSTREAM_UNAVAILABLE,
                message="Upstream provider is unavailable",
                error_type="server_error",
            )
        return _error(
            status_code=400,
            code=ApiErrorCode.UPSTREAM_REJECTED,
            message=exc.message,
            error_type="invalid_request_error",
        )

    return _error(
        status_code=502,
        code=ApiErrorCode.UPSTREAM_UNAVAILABLE,
        message="Upstream provider is unavailable",
        error_type="server_error",
    )


class ChatStream:
    """A chat completion stream whose first chunk was already fetched."""

    def __init__(
        self,
        *,
        first_chunk: ChatCompletionChunk,
        model_id: str,
        upstream: AsyncGenerator[ChatCompletionChunk, None],
    ) -> None:
        self.first_chunk = first_chunk
        self.model_id = model_id
        self._upstream = upstream
        self._closed = False

    async def chunks(self) -> AsyncGenerator[ChatCompletionChunk, None]:
        yield self.first_chunk
        async for chunk in self._upstream:
            yield chunk.model_copy(update={"model": self.model_id})

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._upstream.aclose()
        except RuntimeError:
            # The generator may already be closing because the client
            # disconnected while it was running.
            return


class ChatService:
    def __init__(self, *, models: ModelRepository, providers: ProviderRegistry) -> None:
        self._models = models
        self._providers = providers

    async def resolve_model(self, model_id: str) -> ResolvedModel:
        config = await self._models.get_model(model_id)
        if config is None:
            raise _error(
                status_code=404,
                code=ApiErrorCode.MODEL_NOT_FOUND,
                message=f"Model '{model_id}' was not found",
                error_type="invalid_request_error",
                param="model",
            )
        if not config.enabled:
            raise _error(
                status_code=403,
                code=ApiErrorCode.MODEL_DISABLED,
                message=f"Model '{model_id}' is not available",
                error_type="invalid_request_error",
            )
        try:
            provider = self._providers.get(config.provider)
        except ProviderNotConfiguredError as exc:
            raise _error(
                status_code=503,
                code=ApiErrorCode.PROVIDER_NOT_CONFIGURED,
                message=f"Provider '{config.provider.value}' is not configured",
                error_type="server_error",
            ) from exc
        return ResolvedModel(config=config, provider=provider)

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        resolved = await self.resolve_model(request.model)
        try:
            response = await resolved.provider.complete(
                upstream_model=resolved.config.upstream_model,
                request=request,
            )
        except ProviderError as exc:
            raise map_provider_error(exc) from exc
        return response.model_copy(update={"model": resolved.config.id})

    async def open_stream(self, request: ChatCompletionRequest) -> ChatStream:
        resolved = await self.resolve_model(request.model)
        upstream = resolved.provider.stream(
            upstream_model=resolved.config.upstream_model,
            request=request,
        )
        try:
            first_chunk = await anext(upstream)
        except StopAsyncIteration:
            await upstream.aclose()
            raise _error(
                status_code=502,
                code=ApiErrorCode.UPSTREAM_INVALID_RESPONSE,
                message="Upstream provider returned an empty stream",
                error_type="server_error",
            ) from None
        except ProviderError as exc:
            await upstream.aclose()
            raise map_provider_error(exc) from exc

        return ChatStream(
            first_chunk=first_chunk.model_copy(update={"model": resolved.config.id}),
            model_id=resolved.config.id,
            upstream=upstream,
        )
