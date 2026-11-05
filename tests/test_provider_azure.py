from __future__ import annotations

from datetime import UTC, datetime

import httpx

from llm_gateway.providers.azure import AzureOpenAIProvider
from llm_gateway.providers.retry import RetryPolicy
from llm_gateway.schemas.chat import ChatCompletionRequest

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

COMPLETION = {
    "id": "chatcmpl-azure",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hello"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
}


def _provider(base_url: str, captured: dict[str, str]) -> AzureOpenAIProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("api-key", "")
        captured["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=COMPLETION)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AzureOpenAIProvider(
        api_key="azure-secret",
        base_url=base_url,
        deployment="prod/chat",
        api_version="2024-10-21",
        timeout=httpx.Timeout(30.0),
        retry_policy=RetryPolicy(max_attempts=1),
        client=client,
        sleeper=_no_sleep,
    )


async def _no_sleep(_: float) -> None:
    return None


async def test_azure_routes_by_deployment_and_uses_the_api_key_header() -> None:
    captured: dict[str, str] = {}
    provider = _provider("https://example.openai.azure.com", captured)

    response = await provider.complete(
        upstream_model="gpt-4o",
        request=ChatCompletionRequest.model_validate(
            {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
        ),
    )

    assert response.choices[0].message.content == "hello"
    assert captured["url"] == (
        "https://example.openai.azure.com/openai/deployments/prod%2Fchat"
        "/chat/completions?api-version=2024-10-21"
    )
    assert captured["api_key"] == "azure-secret"
    assert captured["authorization"] == ""
    await provider.aclose()


async def test_azure_strips_a_trailing_openai_segment() -> None:
    captured: dict[str, str] = {}
    provider = _provider("https://example.openai.azure.com/openai/", captured)

    await provider.complete(
        upstream_model="gpt-4o",
        request=ChatCompletionRequest.model_validate(
            {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
        ),
    )

    assert captured["url"].startswith("https://example.openai.azure.com/openai/deployments/")
    assert "/openai/openai/" not in captured["url"]
    await provider.aclose()
