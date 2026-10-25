from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from llm_gateway.providers.base import ProviderName
from llm_gateway.schemas.chat import Usage
from llm_gateway.services.usage import extract_token_counts
from llm_gateway.storage.repositories import UsageRecord

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _record(**overrides: object) -> UsageRecord:
    values: dict[str, object] = {
        "id": uuid4(),
        "request_id": "req-1",
        "tenant_id": uuid4(),
        "api_key_id": uuid4(),
        "model_id": "model-1",
        "provider": ProviderName.FAKE,
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
        "cached_tokens": 0,
        "created_at": NOW,
    }
    values.update(overrides)
    return UsageRecord(**values)  # pyright: ignore[reportArgumentType]


def test_extract_token_counts_returns_none_for_missing_usage() -> None:
    assert extract_token_counts(None) is None


def test_extract_token_counts_reads_openai_cached_details() -> None:
    usage = Usage.model_validate(
        {
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "total_tokens": 14,
            "prompt_tokens_details": {"cached_tokens": 6},
        }
    )

    counts = extract_token_counts(usage)

    assert counts is not None
    assert counts.prompt_tokens == 10
    assert counts.completion_tokens == 4
    assert counts.total_tokens == 14
    assert counts.cached_tokens == 6


def test_extract_token_counts_reads_deepseek_cache_hit_tokens() -> None:
    usage = Usage.model_validate(
        {
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "total_tokens": 14,
            "prompt_cache_hit_tokens": 3,
        }
    )

    counts = extract_token_counts(usage)

    assert counts is not None
    assert counts.cached_tokens == 3


def test_extract_token_counts_defaults_missing_cache_to_zero() -> None:
    counts = extract_token_counts(Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    assert counts is not None
    assert counts.cached_tokens == 0


@pytest.mark.parametrize(
    "details",
    [
        {"cached_tokens": -1},
        {"cached_tokens": "4"},
        {"cached_tokens": True},
        {"cached_tokens": None},
        {"other": 4},
        "not-a-dict",
        None,
    ],
)
def test_extract_token_counts_ignores_malformed_cache_shapes(details: object) -> None:
    usage = Usage.model_validate(
        {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
            "prompt_tokens_details": details,
        }
    )

    counts = extract_token_counts(usage)

    assert counts is not None
    assert counts.cached_tokens == 0


@pytest.mark.parametrize(
    "cache_hit",
    [-1, "3", True, None],
)
def test_extract_token_counts_ignores_malformed_deepseek_cache(cache_hit: object) -> None:
    usage = Usage.model_validate(
        {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
            "prompt_cache_hit_tokens": cache_hit,
        }
    )

    counts = extract_token_counts(usage)

    assert counts is not None
    assert counts.cached_tokens == 0


def test_usage_record_accepts_valid_values() -> None:
    record = _record()

    assert record.total_tokens == 3


def test_usage_record_rejects_negative_tokens() -> None:
    with pytest.raises(ValueError, match="prompt_tokens"):
        _record(prompt_tokens=-1)


def test_usage_record_rejects_naive_created_at() -> None:
    with pytest.raises(ValueError, match="created_at"):
        _record(created_at=datetime(2026, 1, 2, 3, 4, 5))  # noqa: DTZ001 - naive under test


def test_usage_record_rejects_blank_request_id() -> None:
    with pytest.raises(ValueError, match="request_id"):
        _record(request_id="   ")
