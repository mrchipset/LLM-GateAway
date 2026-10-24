from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from llm_gateway.auth.keys import generate_api_key
from llm_gateway.container import Container
from llm_gateway.providers.base import ProviderName
from llm_gateway.storage.repositories import ModelConfig

FROZEN_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


class FrozenClock:
    """Clock that always reports a fixed timezone-aware instant."""

    def __init__(self, now: datetime = FROZEN_NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


async def seed_model(
    container: Container,
    *,
    model_id: str = "fake-model",
    provider: ProviderName = ProviderName.FAKE,
    upstream_model: str | None = None,
    created_at: datetime | None = None,
    enabled: bool = True,
) -> ModelConfig:
    model = ModelConfig(
        id=model_id,
        provider=provider,
        upstream_model=upstream_model if upstream_model is not None else f"upstream-{model_id}",
        created_at=created_at if created_at is not None else container.clock.now(),
        enabled=enabled,
    )
    await container.models.create_model(model)
    return model


async def seed_api_key(container: Container, *, name: str = "test key") -> str:
    secret, record = generate_api_key(
        key_id=uuid4(),
        name=name,
        now=container.clock.now(),
    )
    await container.api_keys.create_key(record)
    return secret
