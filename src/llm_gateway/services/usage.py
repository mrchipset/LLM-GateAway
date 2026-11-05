from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from llm_gateway.clock import Clock
from llm_gateway.logging import get_logger
from llm_gateway.metrics import current_metrics
from llm_gateway.providers.base import ProviderName
from llm_gateway.schemas.chat import Usage
from llm_gateway.services.billing import BillingAllowance, compute_usage_cost
from llm_gateway.storage.rate_limits import BucketScope, RateLimiter, RateLimiterUnavailable
from llm_gateway.storage.repositories import UsageRecord, UsageRepository
from llm_gateway.telemetry import current_trace_id

logger = get_logger(__name__)

USAGE_WRITE_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class TokenLimits:
    """Configured TPM limits to settle after the response reports usage."""

    tenant_tokens_per_minute: int | None = None
    key_tokens_per_minute: int | None = None
    model_tokens_per_minute: int | None = None


@dataclass(frozen=True, slots=True)
class TokenCounts:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _openai_cached_tokens(usage: Usage) -> int | None:
    details = getattr(usage, "prompt_tokens_details", None)
    if not isinstance(details, dict):
        return None
    return _non_negative_int(details.get("cached_tokens"))


def _deepseek_cached_tokens(usage: Usage) -> int | None:
    return _non_negative_int(getattr(usage, "prompt_cache_hit_tokens", None))


def extract_token_counts(usage: Usage | None) -> TokenCounts | None:
    """Normalize provider usage payloads into stable token counts."""
    if usage is None:
        return None

    cached = _openai_cached_tokens(usage)
    if cached is None:
        cached = _deepseek_cached_tokens(usage)
    return TokenCounts(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        cached_tokens=cached if cached is not None else 0,
    )


@dataclass(frozen=True, slots=True)
class UsageContext:
    request_id: str
    tenant_id: UUID
    api_key_id: UUID
    model_id: str
    provider: ProviderName
    allowance: BillingAllowance | None = None
    token_limits: TokenLimits | None = None


class UsageRecorder:
    def __init__(
        self,
        *,
        repository: UsageRepository,
        clock: Clock,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._rate_limiter = rate_limiter

    async def record(self, *, context: UsageContext, usage: Usage) -> None:
        counts = extract_token_counts(usage)
        if counts is None:
            raise ValueError("usage must not be None")

        cost = compute_usage_cost(
            prompt_tokens=counts.prompt_tokens,
            cached_tokens=counts.cached_tokens,
            completion_tokens=counts.completion_tokens,
            allowance=context.allowance,
        )
        record = UsageRecord(
            id=uuid4(),
            request_id=context.request_id,
            tenant_id=context.tenant_id,
            api_key_id=context.api_key_id,
            model_id=context.model_id,
            provider=context.provider,
            prompt_tokens=counts.prompt_tokens,
            completion_tokens=counts.completion_tokens,
            total_tokens=counts.total_tokens,
            cached_tokens=counts.cached_tokens,
            created_at=self._clock.now(),
            trace_id=current_trace_id(),
            covered_tokens=cost.covered_tokens,
            billable_tokens=cost.billable_tokens,
            list_cost=cost.list_cost,
            billed_cost=cost.billed_cost,
        )
        await self._repository.record(record)
        await self._settle_tokens(
            context=context,
            tokens=counts.prompt_tokens + counts.completion_tokens,
            now=record.created_at,
        )

    async def _settle_tokens(
        self,
        *,
        context: UsageContext,
        tokens: int,
        now: datetime,
    ) -> None:
        """Charge reported tokens against TPM buckets; never fail the request."""
        limits = context.token_limits
        if limits is None or self._rate_limiter is None or tokens <= 0:
            return
        charges: tuple[tuple[BucketScope, str, int | None], ...] = (
            ("tenant", f"{context.tenant_id}:tpm", limits.tenant_tokens_per_minute),
            ("key", f"{context.api_key_id}:tpm", limits.key_tokens_per_minute),
            ("model", f"{context.model_id}:tpm", limits.model_tokens_per_minute),
        )
        for scope, key, limit in charges:
            if limit is None:
                continue
            try:
                await self._rate_limiter.consume(
                    scope=scope,
                    key=key,
                    limit=limit,
                    now=now,
                    cost=tokens,
                )
            except RateLimiterUnavailable as exc:
                current_metrics().rate_limit_degraded.add(1, {"reason": exc.reason})
                logger.warning(
                    "token_rate_limit_settlement_failed",
                    extra={
                        "scope": scope,
                        "tenant_id": str(context.tenant_id),
                        "reason": exc.reason,
                    },
                )


async def record_usage_safely(
    *,
    recorder: UsageRecorder,
    context: UsageContext,
    usage: Usage | None,
    timeout_seconds: float = USAGE_WRITE_TIMEOUT_SECONDS,
) -> None:
    """Persist usage without ever failing the client-facing response."""
    if usage is None:
        logger.warning(
            "usage_unavailable",
            extra={
                "request_id": context.request_id,
                "model_id": context.model_id,
            },
        )
        current_metrics().usage_write_failures.add(1, {"reason": "unavailable"})
        return

    try:
        async with asyncio.timeout(timeout_seconds):
            await recorder.record(context=context, usage=usage)
    except Exception as exc:
        logger.warning(
            "usage_record_failed",
            extra={
                "request_id": context.request_id,
                "model_id": context.model_id,
                "error": type(exc).__name__,
            },
        )
        current_metrics().usage_write_failures.add(1, {"reason": "write_failed"})
