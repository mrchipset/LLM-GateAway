from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx

from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.providers.throughput import record_stream_throughput, reset_throughput_window
from llm_gateway.schemas.chat import Usage


def _usage() -> Usage:
    return Usage(prompt_tokens=100, completion_tokens=11, total_tokens=111)


async def test_throughput_endpoint_requires_authentication(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container = make_container(settings)

    async with make_client(settings, container) as client:
        response = await client.get("/api/v1/throughput")

    assert response.status_code == 401


async def test_throughput_endpoint_returns_recent_samples(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    reset_throughput_window()
    try:
        record_stream_throughput(
            provider="openai",
            model="qwen3",
            span=None,
            usage=_usage(),
            ttft_seconds=1.0,
            decode_seconds=2.0,
        )
        container = make_container(settings)
        master = settings.master_key.get_secret_value()

        async with make_client(settings, container) as client:
            response = await client.get(
                "/api/v1/throughput",
                headers={"Authorization": f"Bearer {master}"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["window_seconds"] == 900
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["provider"] == "openai"
        assert item["model"] == "qwen3"
        assert item["samples"] == 1
        assert item["prefill_tokens_per_second_p50"] == 100.0
        assert item["prefill_tokens_per_second_p95"] == 100.0
        assert item["decode_tokens_per_second_p50"] == 5.0
        assert item["decode_tokens_per_second_p95"] == 5.0
        assert item["last_observed_at"] is not None
    finally:
        reset_throughput_window()
