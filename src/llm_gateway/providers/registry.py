from __future__ import annotations

from collections.abc import Mapping

from llm_gateway.providers.base import ChatProvider, ProviderName, ProviderNotConfiguredError


class ProviderRegistry:
    """Immutable name -> provider mapping built once at startup."""

    def __init__(self, providers: Mapping[ProviderName, ChatProvider]) -> None:
        self._providers: dict[ProviderName, ChatProvider] = dict(providers)

    def get(self, name: ProviderName) -> ChatProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise ProviderNotConfiguredError(name)
        return provider

    def is_configured(self, name: ProviderName) -> bool:
        return name in self._providers

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()
