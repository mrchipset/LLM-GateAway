from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from llm_gateway.providers.base import ProviderName


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
