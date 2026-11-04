"""Provider instances for deployments.

Deployments never store secrets. A deployment may name an environment variable via
``credential_env`` and/or override ``base_url``; the pool resolves the secret from the
process environment and caches one HTTP client per (provider, env var, base URL).

When a deployment has no overrides it reuses the provider built from settings, so the
single-upstream path is unchanged.
"""

from __future__ import annotations

import os

import httpx

from llm_gateway.config import Settings
from llm_gateway.providers.base import ChatProvider, ProviderName, ProviderNotConfiguredError
from llm_gateway.providers.openai import OpenAIProvider
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.providers.retry import RetryPolicy
from llm_gateway.storage.repositories import ModelDeployment


class DeploymentCredentialError(Exception):
    def __init__(self, deployment_name: str, env_var: str) -> None:
        super().__init__(
            f"deployment '{deployment_name}' needs environment variable {env_var}, which is empty"
        )
        self.deployment_name = deployment_name
        self.env_var = env_var


class ProviderPool:
    def __init__(
        self,
        *,
        settings: Settings,
        providers: ProviderRegistry,
        tracer: object | None = None,
    ) -> None:
        self._settings = settings
        self._providers = providers
        self._tracer = tracer
        self._clients: dict[tuple[str, str | None, str | None], OpenAIProvider] = {}

    def get(self, deployment: ModelDeployment) -> ChatProvider:
        if deployment.provider is ProviderName.FAKE:
            return self._providers.get(ProviderName.FAKE)

        has_override = deployment.credential_env is not None or deployment.base_url is not None
        if not has_override:
            return self._providers.get(deployment.provider)

        key = (deployment.provider.value, deployment.credential_env, deployment.base_url)
        cached = self._clients.get(key)
        if cached is not None:
            return cached

        api_key = self._resolve_key(deployment)
        base_url = self._resolve_base_url(deployment)
        provider = OpenAIProvider(
            name=deployment.provider,
            api_key=api_key,
            base_url=base_url,
            timeout=httpx.Timeout(
                self._settings.request_timeout_seconds,
                connect=self._settings.connect_timeout_seconds,
            ),
            retry_policy=RetryPolicy(max_attempts=self._settings.max_retries + 1),
            tracer=self._tracer,  # pyright: ignore[reportArgumentType]
        )
        self._clients[key] = provider
        return provider

    def _resolve_key(self, deployment: ModelDeployment) -> str:
        if deployment.credential_env is not None:
            value = os.environ.get(deployment.credential_env)
            if not value:
                raise DeploymentCredentialError(deployment.name, deployment.credential_env)
            return value

        if deployment.provider is ProviderName.OPENAI and self._settings.openai_api_key:
            return self._settings.openai_api_key.get_secret_value()
        if deployment.provider is ProviderName.DEEPSEEK and self._settings.deepseek_api_key:
            return self._settings.deepseek_api_key.get_secret_value()
        raise ProviderNotConfiguredError(deployment.provider)

    def _resolve_base_url(self, deployment: ModelDeployment) -> str:
        if deployment.base_url is not None:
            return deployment.base_url
        if deployment.provider is ProviderName.OPENAI:
            return self._settings.openai_base_url
        if deployment.provider is ProviderName.DEEPSEEK:
            return self._settings.deepseek_base_url
        raise ProviderNotConfiguredError(deployment.provider)

    async def aclose(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.aclose()
