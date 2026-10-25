from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from llm_gateway.providers.base import ProviderName
from llm_gateway.storage.repositories import TimeBucket


class UsageModelSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    provider: ProviderName
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    requests: int


class UsageSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    requests: int
    by_model: list[UsageModelSummary]


class KeyUsageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key_id: UUID
    name: str | None = None
    key_prefix: str | None = None
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    requests: int


class KeyUsageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[KeyUsageSummary]
    limit: int


class UsagePointSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bucket_start: datetime
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    total_tokens: int
    requests: int


class UsageSeriesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bucket: TimeBucket
    points: list[UsagePointSummary]
