"""Cost accounting and plan enforcement.

Two numbers are tracked for every request:

* ``list_cost`` — what the usage would cost at list price. Always computed when a
  price exists, so margin is visible even for plan-covered traffic.
* ``billed_cost`` — what the tenant owes. Zero inside a monthly token plan,
  list price for the part that exceeds it.

The plan is a token allowance, but prices are per token category, so the allowance
is split across categories pro rata to the request's own mix. That avoids a cliff
where the request crossing the boundary pays full price for every token, and it
keeps the split deterministic and explainable.

Concurrency caveat: enforcement reads the period total before the request runs and
settles afterwards. Concurrent in-flight requests can therefore overshoot by at
most their own usage. This matches the existing token-quota semantics; atomic
reservation is a later step (TODO G1.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.logging import get_logger
from llm_gateway.metrics import current_metrics
from llm_gateway.storage.repositories import (
    ModelPrice,
    ModelPriceRepository,
    MonthlyUsage,
    Tenant,
    UsageRepository,
)

logger = get_logger(__name__)

MONEY_QUANTUM = Decimal("0.000001")
TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)


def month_window(now: datetime) -> tuple[datetime, datetime]:
    """Return the half-open UTC calendar-month window containing ``now``."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    month_start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)
    return month_start, next_month_start


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class BillingAllowance:
    """Snapshot taken before the request; used to settle costs afterwards."""

    price: ModelPrice | None = None
    remaining_plan_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class UsageCost:
    covered_tokens: int
    billable_tokens: int
    list_cost: Decimal | None
    billed_cost: Decimal | None


def split_allowance(buckets: tuple[int, ...], covered: int) -> tuple[int, ...]:
    """Split ``covered`` tokens across ``buckets`` pro rata, in whole tokens.

    Floor everything, then hand the remainder to the largest fractional parts
    (ties break on bucket order) so the parts always sum to exactly ``covered``.
    """
    total = sum(buckets)
    if total <= 0 or covered <= 0:
        return tuple(0 for _ in buckets)
    if covered >= total:
        return buckets

    exact = [Fraction(bucket * covered, total) for bucket in buckets]
    parts = [int(value) for value in exact]
    remainder = covered - sum(parts)
    order = sorted(
        range(len(buckets)),
        key=lambda index: (-(exact[index] - parts[index]), index),
    )
    for index in order[:remainder]:
        parts[index] += 1
    return tuple(parts)


def _bucket_cost(tokens: int, per_million: Decimal) -> Decimal:
    return Decimal(tokens) * per_million / TOKENS_PER_PRICE_UNIT


def _price_buckets(
    buckets: tuple[int, ...],
    price: ModelPrice,
) -> Decimal:
    cached_price = (
        price.cached_input_per_million
        if price.cached_input_per_million is not None
        else price.input_per_million
    )
    uncached_prompt, cached, completion = buckets
    return quantize_money(
        _bucket_cost(uncached_prompt, price.input_per_million)
        + _bucket_cost(cached, cached_price)
        + _bucket_cost(completion, price.output_per_million)
    )


def compute_usage_cost(
    *,
    prompt_tokens: int,
    cached_tokens: int,
    completion_tokens: int,
    allowance: BillingAllowance | None,
) -> UsageCost:
    """Turn reported tokens into covered/billable tokens and money.

    Billing uses ``prompt + completion`` as the token measure; ``total_tokens``
    reported upstream is kept for reporting only, because some providers include
    extra buckets in it.
    """
    cached = min(max(cached_tokens, 0), max(prompt_tokens, 0))
    buckets = (max(prompt_tokens, 0) - cached, cached, max(completion_tokens, 0))
    total = sum(buckets)

    price = allowance.price if allowance is not None else None
    if price is None:
        return UsageCost(
            covered_tokens=0,
            billable_tokens=total,
            list_cost=None,
            billed_cost=None,
        )

    remaining = allowance.remaining_plan_tokens if allowance is not None else None
    covered = 0 if remaining is None else min(max(remaining, 0), total)
    covered_buckets = split_allowance(buckets, covered)
    billable_buckets = tuple(
        bucket - covered_bucket
        for bucket, covered_bucket in zip(buckets, covered_buckets, strict=True)
    )

    return UsageCost(
        covered_tokens=sum(covered_buckets),
        billable_tokens=sum(billable_buckets),
        list_cost=_price_buckets(buckets, price),
        billed_cost=_price_buckets(billable_buckets, price),
    )


def budget_remaining(tenant: Tenant, usage: MonthlyUsage) -> Decimal | None:
    if tenant.monthly_cost_budget is None:
        return None
    remaining = tenant.monthly_cost_budget - usage.billed_cost
    return quantize_money(max(remaining, Decimal("0")))


class BillingService:
    """Reads the period state and decides whether a request may proceed."""

    def __init__(
        self,
        *,
        usage: UsageRepository,
        prices: ModelPriceRepository,
    ) -> None:
        self._usage = usage
        self._prices = prices

    async def authorize(
        self,
        *,
        tenant: Tenant,
        model_id: str,
        now: datetime,
    ) -> BillingAllowance | None:
        """Return the allowance snapshot, or ``None`` when the tenant is unbilled.

        Raises 429 when the plan or the budget is exhausted, and 503 when the
        tenant is billed but the model has no price: a budget that cannot be
        computed must not silently pass traffic.
        """
        if tenant.plan_tokens is None and tenant.monthly_cost_budget is None:
            return None

        period_start, period_end = month_window(now)
        totals = await self._usage.monthly_totals(
            tenant_id=tenant.id,
            since=period_start,
            until=period_end,
        )

        if tenant.plan_tokens is not None:
            remaining = max(tenant.plan_tokens - totals.total_tokens, 0)
            if remaining == 0 and not tenant.plan_allow_overage:
                logger.warning(
                    "plan_allowance_exhausted",
                    extra={
                        "tenant_id": str(tenant.id),
                        "plan_tokens": tenant.plan_tokens,
                        "used_tokens": totals.total_tokens,
                    },
                )
                current_metrics().rejections.add(1, {"reason": "plan_allowance"})
                raise _plan_exhausted()
        else:
            remaining = None

        if (
            tenant.monthly_cost_budget is not None
            and totals.billed_cost >= tenant.monthly_cost_budget
        ):
            logger.warning(
                "budget_exceeded",
                extra={
                    "tenant_id": str(tenant.id),
                    "budget": str(tenant.monthly_cost_budget),
                    "billed_cost": str(totals.billed_cost),
                },
            )
            current_metrics().rejections.add(1, {"reason": "budget"})
            raise _budget_exhausted()

        price = await self._prices.get_effective_price(model_id=model_id, at=now)
        if price is None:
            logger.error(
                "model_price_missing",
                extra={"tenant_id": str(tenant.id), "model_id": model_id},
            )
            current_metrics().rejections.add(1, {"reason": "price_missing"})
            raise ApiError(
                status_code=503,
                code=ApiErrorCode.MODEL_PRICE_MISSING,
                message=f"Model '{model_id}' has no price configured",
                error_type="server_error",
            )
        return BillingAllowance(price=price, remaining_plan_tokens=remaining)


def _plan_exhausted() -> ApiError:
    return ApiError(
        status_code=429,
        code=ApiErrorCode.PLAN_ALLOWANCE_EXHAUSTED,
        message="Tenant monthly plan allowance is exhausted",
        error_type="insufficient_quota",
    )


def _budget_exhausted() -> ApiError:
    return ApiError(
        status_code=429,
        code=ApiErrorCode.BUDGET_EXCEEDED,
        message="Tenant monthly cost budget is exhausted",
        error_type="insufficient_quota",
    )
