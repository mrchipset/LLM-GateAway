from __future__ import annotations

import httpx

from llm_gateway.clock import Clock
from llm_gateway.config import Settings
from llm_gateway.providers.base import ChatProvider, ProviderName
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.providers.openai import OpenAIProvider
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.providers.retry import RetryPolicy


def build_providers(settings: Settings, *, clock: Clock) -> ProviderRegistry:
    providers: dict[ProviderName, ChatProvider] = {}

    if settings.openai_api_key is not None:
        providers[ProviderName.OPENAI] = OpenAIProvider(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
            timeout=httpx.Timeout(
                settings.request_timeout_seconds,
                connect=settings.connect_timeout_seconds,
            ),
            retry_policy=RetryPolicy(max_attempts=settings.max_retries + 1),
        )

    if settings.fake_provider_enabled:
        providers[ProviderName.FAKE] = FakeProvider(clock=clock)

    return ProviderRegistry(providers)
