from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from pydantic import SecretStr

from llm_gateway.clock import Clock
from llm_gateway.config import Settings
from llm_gateway.providers.anthropic import AnthropicProvider
from llm_gateway.providers.base import ChatProvider, ProviderName
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.providers.openai import OpenAIProvider
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.providers.retry import RetryPolicy

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer


def _openai_compatible_provider(
    *,
    name: ProviderName,
    api_key: SecretStr,
    base_url: str,
    settings: Settings,
    tracer: Tracer | None,
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
        tracer=tracer,
        stream_idle_timeout_seconds=settings.stream_idle_timeout_seconds,
    )


def build_providers(
    settings: Settings,
    *,
    clock: Clock,
    tracer: Tracer | None = None,
) -> ProviderRegistry:
    providers: dict[ProviderName, ChatProvider] = {}

    if settings.openai_api_key is not None:
        providers[ProviderName.OPENAI] = _openai_compatible_provider(
            name=ProviderName.OPENAI,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            settings=settings,
            tracer=tracer,
        )

    if settings.deepseek_api_key is not None:
        providers[ProviderName.DEEPSEEK] = _openai_compatible_provider(
            name=ProviderName.DEEPSEEK,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            settings=settings,
            tracer=tracer,
        )

    if settings.anthropic_api_key is not None:
        providers[ProviderName.ANTHROPIC] = AnthropicProvider(
            api_key=settings.anthropic_api_key.get_secret_value(),
            base_url=settings.anthropic_base_url,
            version=settings.anthropic_version,
            default_max_tokens=settings.anthropic_default_max_tokens,
            timeout=httpx.Timeout(
                settings.request_timeout_seconds,
                connect=settings.connect_timeout_seconds,
            ),
            retry_policy=RetryPolicy(max_attempts=settings.max_retries + 1),
            tracer=tracer,
            stream_idle_timeout_seconds=settings.stream_idle_timeout_seconds,
        )

    if settings.fake_provider_enabled:
        providers[ProviderName.FAKE] = FakeProvider(clock=clock)

    return ProviderRegistry(providers)
