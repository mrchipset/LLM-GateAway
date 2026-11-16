from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ThroughputStatsItem(BaseModel):
    """Recent effective throughput for one provider/model pair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    samples: int = Field(ge=0)
    prefill_tokens_per_second_p50: float | None = None
    prefill_tokens_per_second_p95: float | None = None
    decode_tokens_per_second_p50: float | None = None
    decode_tokens_per_second_p95: float | None = None
    last_observed_at: datetime | None = None


class ThroughputResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window_seconds: int
    items: list[ThroughputStatsItem]
