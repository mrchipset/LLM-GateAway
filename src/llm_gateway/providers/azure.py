"""Azure OpenAI deployment adapter.

Azure exposes the same chat-completions payload as OpenAI but routes by deployment
name in the path, authenticates with the ``api-key`` header, and requires an
``api-version`` query parameter. Everything else is inherited from the OpenAI
adapter.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx
from opentelemetry.trace import Tracer

from llm_gateway.providers.base import ProviderName
from llm_gateway.providers.openai import OpenAIProvider
from llm_gateway.providers.retry import RetryPolicy, Sleeper, asyncio_sleep


class AzureOpenAIProvider(OpenAIProvider):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        deployment: str,
        api_version: str,
        timeout: httpx.Timeout,
        retry_policy: RetryPolicy,
        client: httpx.AsyncClient | None = None,
        sleeper: Sleeper = asyncio_sleep,
        tracer: Tracer | None = None,
        stream_idle_timeout_seconds: float = 0.0,
    ) -> None:
        super().__init__(
            name=ProviderName.AZURE,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            retry_policy=retry_policy,
            client=client,
            sleeper=sleeper,
            tracer=tracer,
            stream_idle_timeout_seconds=stream_idle_timeout_seconds,
        )
        resource = base_url.rstrip("/")
        if resource.endswith("/openai"):
            resource = resource[: -len("/openai")]
        self._endpoint = (
            f"{resource}/openai/deployments/{quote(deployment, safe='')}"
            f"/chat/completions?api-version={quote(api_version, safe='')}"
        )

    def _request_headers(self) -> dict[str, str]:
        return {
            "api-key": self._api_key,
            "Content-Type": "application/json",
        }
