from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from llm_gateway.auth.keys import generate_api_key
from llm_gateway.container import Container
from llm_gateway.providers.base import ProviderName
from llm_gateway.storage.memory import InMemoryUsageRepository
from llm_gateway.storage.repositories import ModelConfig, Tenant, UsageRecord

FROZEN_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
TEST_TENANT_NAME = "test-tenant"


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


async def seed_tenant(
    container: Container,
    *,
    name: str = TEST_TENANT_NAME,
    tenant_id: UUID | None = None,
    created_at: datetime | None = None,
) -> Tenant:
    tenant = Tenant(
        id=tenant_id if tenant_id is not None else uuid4(),
        name=name,
        created_at=created_at if created_at is not None else container.clock.now(),
    )
    return await container.tenants.create_tenant(tenant)


async def _ensure_test_tenant(container: Container) -> Tenant:
    tenants, _ = await container.tenants.list_tenants(limit=100, offset=0)
    for tenant in tenants:
        if tenant.name == TEST_TENANT_NAME:
            return tenant
    return await seed_tenant(container, name=TEST_TENANT_NAME)


async def seed_api_key(
    container: Container,
    *,
    tenant_id: UUID | None = None,
    name: str = "test key",
) -> str:
    resolved_tenant_id = (
        tenant_id if tenant_id is not None else (await _ensure_test_tenant(container)).id
    )
    secret, record = generate_api_key(
        key_id=uuid4(),
        tenant_id=resolved_tenant_id,
        name=name,
        now=container.clock.now(),
    )
    await container.api_keys.create_key(record)
    return secret


class CapturingUsageRepository(InMemoryUsageRepository):
    """In-memory ledger that exposes the records written during a test."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[UsageRecord] = []

    async def record(self, record: UsageRecord) -> None:
        self.records.append(record)
        await super().record(record)


class FailingUsageRepository(InMemoryUsageRepository):
    async def record(self, record: UsageRecord) -> None:
        raise RuntimeError("usage storage unavailable")


async def seed_usage(
    container: Container,
    *,
    tenant_id: UUID,
    api_key_id: UUID,
    model_id: str,
    provider: ProviderName = ProviderName.FAKE,
    created_at: datetime | None = None,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    cached_tokens: int = 0,
    request_id: str = "req-usage",
) -> UsageRecord:
    record = UsageRecord(
        id=uuid4(),
        request_id=request_id,
        tenant_id=tenant_id,
        api_key_id=api_key_id,
        model_id=model_id,
        provider=provider,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cached_tokens=cached_tokens,
        created_at=created_at if created_at is not None else container.clock.now(),
    )
    await container.usage.record(record)
    return record
