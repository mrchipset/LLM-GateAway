"""Multi-deployment routing with weighted selection, failover, and cooldown.

One public model maps to one or more deployments. A request tries deployments in a
weighted-random order; a retryable failure (timeout, connection, 429/5xx, invalid body) or
an upstream credential rejection moves to the next deployment. Client errors such as 400
do not fail over: the request is wrong everywhere.

Cooldown is process-local. With several workers each process learns independently, which
is acceptable for advisory health and is revisited when rate limiting moves to Redis
(TODO G1.2). A cooldown never removes the last candidate: if everything is cooling down the
router still tries, preferring the deployment whose cooldown expires first, so health state
cannot take the model fully offline.
"""

from __future__ import annotations

import random
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from opentelemetry.trace import Tracer

from llm_gateway.clock import Clock
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.logging import get_logger
from llm_gateway.metrics import current_metrics
from llm_gateway.providers.base import (
    ChatProvider,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderResponseError,
    ProviderUpstreamError,
)
from llm_gateway.providers.pool import DeploymentCredentialError, ProviderPool
from llm_gateway.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Usage,
)
from llm_gateway.storage.repositories import (
    ModelConfig,
    ModelDeployment,
    ModelDeploymentRepository,
    ProviderName,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class DeploymentHealth:
    threshold: int = 3
    cooldown_seconds: int = 30
    _failures: dict[UUID, int] = field(default_factory=dict)
    _cooldown_until: dict[UUID, datetime] = field(default_factory=dict)

    def available(self, deployment_id: UUID, now: datetime) -> bool:
        until = self._cooldown_until.get(deployment_id)
        return until is None or now >= until

    def cooldown_until(self, deployment_id: UUID) -> datetime | None:
        return self._cooldown_until.get(deployment_id)

    def record_success(self, deployment_id: UUID) -> None:
        self._failures.pop(deployment_id, None)
        self._cooldown_until.pop(deployment_id, None)

    def record_failure(self, deployment_id: UUID, now: datetime) -> bool:
        """Return True when this failure triggered a cooldown."""
        failures = self._failures.get(deployment_id, 0) + 1
        if failures < self.threshold:
            self._failures[deployment_id] = failures
            return False
        self._failures[deployment_id] = 0
        self._cooldown_until[deployment_id] = now + timedelta(seconds=self.cooldown_seconds)
        return True


@dataclass(frozen=True, slots=True)
class DeploymentUse:
    name: str
    provider: ProviderName
    upstream_model: str
    fallback: bool
    attempts: int


@dataclass(frozen=True, slots=True)
class RouteCompletion:
    response: ChatCompletionResponse
    deployment: DeploymentUse


@dataclass(frozen=True, slots=True)
class RouteStream:
    upstream: AsyncGenerator[ChatCompletionChunk, None]
    first_chunk: ChatCompletionChunk
    usage: Usage | None
    deployment: DeploymentUse


def weighted_order(deployments: list[ModelDeployment], rng: random.Random) -> list[ModelDeployment]:
    remaining = list(deployments)
    ordered: list[ModelDeployment] = []
    while remaining:
        total = sum(item.weight for item in remaining)
        target = rng.random() * total
        accumulated = 0
        for index, item in enumerate(remaining):
            accumulated += item.weight
            if target <= accumulated:
                ordered.append(remaining.pop(index))
                break
        else:  # pragma: no cover - guarded by the weight sum
            ordered.append(remaining.pop())
    return ordered


def synthetic_deployment(model: ModelConfig) -> ModelDeployment:
    return ModelDeployment(
        id=uuid5(NAMESPACE_URL, f"model:{model.id}:default"),
        model_id=model.id,
        name="default",
        provider=model.provider,
        upstream_model=model.upstream_model,
        weight=1,
        enabled=True,
        created_at=model.created_at,
    )


def _should_failover(error: ProviderError) -> bool:
    if error.retryable:
        return True
    if isinstance(error, ProviderUpstreamError) and error.status_code in (401, 403):
        return True
    return isinstance(error, ProviderResponseError)


class ModelRouter:
    def __init__(
        self,
        *,
        deployments: ModelDeploymentRepository,
        pool: ProviderPool,
        health: DeploymentHealth,
        clock: Clock,
        tracer: Tracer | None = None,
        rng: random.Random | None = None,
        max_attempts: int = 3,
    ) -> None:
        self._deployments = deployments
        self._pool = pool
        self._health = health
        self._clock = clock
        self._tracer = tracer
        self._rng = rng if rng is not None else random.Random()  # noqa: S311 - routing
        self._max_attempts = max(1, max_attempts)

    async def _candidates(self, model: ModelConfig) -> list[ModelDeployment]:
        rows = await self._deployments.list_deployments(model.id)
        if not rows:
            return [synthetic_deployment(model)]

        enabled = [row for row in rows if row.enabled]
        if not enabled:
            raise ApiError(
                status_code=503,
                code=ApiErrorCode.NO_DEPLOYMENT,
                message=f"Model '{model.id}' has no enabled deployment",
                error_type="server_error",
            )

        now = self._clock.now()
        ready = [row for row in enabled if self._health.available(row.id, now)]
        pool = ready or sorted(
            enabled,
            key=lambda row: self._health.cooldown_until(row.id) or now,
        )
        return weighted_order(pool, self._rng)[: self._max_attempts]

    def _provider_for(self, deployment: ModelDeployment) -> ChatProvider:
        return self._pool.get(deployment)

    def _attempt_span(self, deployment: ModelDeployment, attempt: int) -> object:
        if self._tracer is None:
            return _NullSpan()
        return self._tracer.start_span(
            "route.attempt",
            attributes={
                "llm.deployment": deployment.name,
                "llm.provider": deployment.provider.value,
                "llm.upstream_model": deployment.upstream_model,
                "llm.route_attempt": attempt,
            },
        )

    def _record_attempt(
        self,
        *,
        deployment: ModelDeployment,
        model: ModelConfig,
        status: str,
        attempt: int,
        span: object,
    ) -> None:
        current_metrics().route_attempts.add(
            1,
            {
                "provider": deployment.provider.value,
                "model": model.id,
                "deployment": deployment.name,
                "status": status,
            },
        )
        if isinstance(span, _NullSpan):
            return
        span.set_attribute("llm.route_status", status)  # pyright: ignore[reportAttributeAccessIssue]
        span.end()  # pyright: ignore[reportAttributeAccessIssue]

    def _mark_failure(self, deployment: ModelDeployment, error: ProviderError) -> None:
        if not _should_failover(error):
            return
        if self._health.record_failure(deployment.id, self._clock.now()):
            current_metrics().deployment_cooldowns.add(1, {"deployment": deployment.name})
            logger.warning(
                "deployment_cooldown",
                extra={
                    "deployment": deployment.name,
                    "provider": deployment.provider.value,
                },
            )

    async def complete(
        self, *, model: ModelConfig, request: ChatCompletionRequest
    ) -> RouteCompletion:
        candidates = await self._candidates(model)
        last_error: Exception | None = None

        for index, deployment in enumerate(candidates):
            attempt = index + 1
            span = self._attempt_span(deployment, attempt)
            try:
                provider = self._provider_for(deployment)
                response = await provider.complete(
                    upstream_model=deployment.upstream_model,
                    request=request,
                )
            except DeploymentCredentialError as exc:
                self._record_attempt(
                    deployment=deployment,
                    model=model,
                    status="credential_error",
                    attempt=attempt,
                    span=span,
                )
                last_error = exc
                continue
            except ProviderNotConfiguredError as exc:
                self._record_attempt(
                    deployment=deployment,
                    model=model,
                    status="not_configured",
                    attempt=attempt,
                    span=span,
                )
                last_error = exc
                continue
            except ProviderError as exc:
                self._record_attempt(
                    deployment=deployment,
                    model=model,
                    status="error",
                    attempt=attempt,
                    span=span,
                )
                self._mark_failure(deployment, exc)
                if _should_failover(exc) and attempt < len(candidates):
                    last_error = exc
                    continue
                raise

            self._health.record_success(deployment.id)
            self._record_attempt(
                deployment=deployment,
                model=model,
                status="success",
                attempt=attempt,
                span=span,
            )
            if index > 0:
                current_metrics().route_fallbacks.add(1, {"model": model.id})
            return RouteCompletion(
                response=response,
                deployment=DeploymentUse(
                    name=deployment.name,
                    provider=deployment.provider,
                    upstream_model=deployment.upstream_model,
                    fallback=index > 0,
                    attempts=attempt,
                ),
            )

        raise self._exhausted(model, last_error)

    async def open_stream(
        self, *, model: ModelConfig, request: ChatCompletionRequest
    ) -> RouteStream:
        candidates = await self._candidates(model)
        last_error: Exception | None = None

        for index, deployment in enumerate(candidates):
            attempt = index + 1
            span = self._attempt_span(deployment, attempt)
            try:
                provider = self._provider_for(deployment)
                upstream = provider.stream(
                    upstream_model=deployment.upstream_model,
                    request=request,
                )
                first_chunk, usage = await _prefetch(upstream)
            except DeploymentCredentialError as exc:
                self._record_attempt(
                    deployment=deployment,
                    model=model,
                    status="credential_error",
                    attempt=attempt,
                    span=span,
                )
                last_error = exc
                continue
            except ProviderNotConfiguredError as exc:
                self._record_attempt(
                    deployment=deployment,
                    model=model,
                    status="not_configured",
                    attempt=attempt,
                    span=span,
                )
                last_error = exc
                continue
            except ProviderError as exc:
                self._record_attempt(
                    deployment=deployment,
                    model=model,
                    status="error",
                    attempt=attempt,
                    span=span,
                )
                self._mark_failure(deployment, exc)
                if _should_failover(exc) and attempt < len(candidates):
                    last_error = exc
                    continue
                raise

            self._health.record_success(deployment.id)
            self._record_attempt(
                deployment=deployment,
                model=model,
                status="success",
                attempt=attempt,
                span=span,
            )
            if index > 0:
                current_metrics().route_fallbacks.add(1, {"model": model.id})
            return RouteStream(
                upstream=upstream,
                first_chunk=first_chunk,
                usage=usage,
                deployment=DeploymentUse(
                    name=deployment.name,
                    provider=deployment.provider,
                    upstream_model=deployment.upstream_model,
                    fallback=index > 0,
                    attempts=attempt,
                ),
            )

        raise self._exhausted(model, last_error)

    def _exhausted(self, model: ModelConfig, last_error: Exception | None) -> Exception:
        if isinstance(last_error, ProviderError):
            return last_error
        if isinstance(last_error, DeploymentCredentialError):
            return ApiError(
                status_code=503,
                code=ApiErrorCode.DEPLOYMENT_CREDENTIAL_MISSING,
                message="No deployment for this model has usable credentials",
                error_type="server_error",
            )
        if isinstance(last_error, ProviderNotConfiguredError):
            return ApiError(
                status_code=503,
                code=ApiErrorCode.PROVIDER_NOT_CONFIGURED,
                message=f"Provider '{last_error.provider.value}' is not configured",
                error_type="server_error",
            )
        return ApiError(
            status_code=503,
            code=ApiErrorCode.NO_DEPLOYMENT,
            message=f"Model '{model.id}' has no usable deployment",
            error_type="server_error",
        )


async def _prefetch(
    upstream: AsyncGenerator[ChatCompletionChunk, None],
) -> tuple[ChatCompletionChunk, Usage | None]:
    first_chunk: ChatCompletionChunk | None = None
    usage: Usage | None = None
    try:
        while first_chunk is None:
            chunk = await anext(upstream)
            if chunk.usage is not None:
                usage = chunk.usage
            if chunk.choices:
                first_chunk = chunk
    except StopAsyncIteration:
        await _close(upstream)
        raise ProviderResponseError("Upstream provider returned an empty stream") from None
    except BaseException:
        await _close(upstream)
        raise
    return first_chunk, usage


async def _close(upstream: AsyncGenerator[ChatCompletionChunk, None]) -> None:
    import anyio

    with anyio.CancelScope(shield=True):
        await upstream.aclose()


class _NullSpan:
    def set_attribute(self, _: str, __: object) -> None:
        return None

    def end(self) -> None:
        return None
