from __future__ import annotations

import httpx
from pydantic import SecretStr

from llm_gateway.clock import Clock
from llm_gateway.config import Settings
from llm_gateway.providers.base import ChatProvider, ProviderName
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.providers.openai import OpenAIProvider
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.providers.retry import RetryPolicy


def _openai_compatible_provider(
    *,
    name: ProviderName,
    api_key: SecretStr,
    base_url: str,
    settings: Settings,
) -> OpenAIProvider:
    return OpenAIProvider(
        name=name,
        api_key=api_key.get_secret_value(),
        base_url=base_url,
        timeout=httpx.Timeout(
            settings.request_timeout_seconds,
            connect=settings.connect_timeout_seconds,
        ),
        retry_policy=RetryPolicy(max_attempts=settings.max_retries + 1),
    )


def build_providers(settings: Settings, *, clock: Clock) -> ProviderRegistry:
    providers: dict[ProviderName, ChatProvider] = {}

    if settings.openai_api_key is not None:
        providers[ProviderName.OPENAI] = _openai_compatible_provider(
            name=ProviderName.OPENAI,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            settings=settings,
        )

    if settings.deepseek_api_key is not None:
        providers[ProviderName.DEEPSEEK] = _openai_compatible_provider(
            name=ProviderName.DEEPSEEK,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            settings=settings,
        )

    if settings.fake_provider_enabled:
        providers[ProviderName.FAKE] = FakeProvider(clock=clock)

    return ProviderRegistry(providers)
