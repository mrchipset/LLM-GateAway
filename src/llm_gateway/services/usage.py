from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

from llm_gateway.clock import Clock
from llm_gateway.logging import get_logger
from llm_gateway.providers.base import ProviderName
from llm_gateway.schemas.chat import Usage
from llm_gateway.storage.repositories import UsageRecord, UsageRepository

logger = get_logger(__name__)

USAGE_WRITE_TIMEOUT_SECONDS = 2.0


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


class UsageRecorder:
    def __init__(self, *, repository: UsageRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def record(self, *, context: UsageContext, usage: Usage) -> None:
        counts = extract_token_counts(usage)
        if counts is None:
            raise ValueError("usage must not be None")

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
        )
        await self._repository.record(record)


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
