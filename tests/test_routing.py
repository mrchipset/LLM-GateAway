from __future__ import annotations

import random
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from llm_gateway.config import Settings
from llm_gateway.container import build_container
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.providers.base import (
    ProviderError,
    ProviderName,
    ProviderResponseError,
    ProviderUpstreamError,
)
from llm_gateway.providers.pool import DeploymentCredentialError
from llm_gateway.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatDelta,
    ChatMessage,
)
from llm_gateway.services.routing import (
    DeploymentHealth,
    ModelRouter,
    weighted_order,
)
from llm_gateway.storage.memory import InMemoryModelDeploymentRepository
from llm_gateway.storage.repositories import ModelConfig, ModelDeployment

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
MODEL_ID = "routed-model"


class FrozenClock:
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class ZeroRandom(random.Random):
    """Always picks the first remaining deployment."""

    def random(self) -> float:
        return 0.0


class StubProvider:
    name = ProviderName.OPENAI

    def __init__(
        self,
        *,
        error: ProviderError | None = None,
        stream_error: ProviderError | None = None,
        text: str = "ok",
    ) -> None:
        self._error = error
        self._stream_error = stream_error
        self._text = text
        self.complete_calls = 0
        self.stream_calls = 0

    async def complete(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        self.complete_calls += 1
        if self._error is not None:
            raise self._error
        return ChatCompletionResponse(
            id="chatcmpl-stub",
            created=1,
            model=upstream_model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=self._text),
                    finish_reason="stop",
                )
            ],
        )

    async def stream(
        self, *, upstream_model: str, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        self.stream_calls += 1
        if self._stream_error is not None:
            raise self._stream_error
        yield ChatCompletionChunk(
            id="chunk-1",
            created=1,
            model=upstream_model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatDelta(content=self._text),
                    finish_reason=None,
                )
            ],
        )

    async def aclose(self) -> None:
        return None


class FakePool:
    def __init__(self, providers: dict[str, StubProvider | Exception]) -> None:
        self._providers = providers

    def get(self, deployment: ModelDeployment) -> StubProvider:
        value = self._providers[deployment.name]
        if isinstance(value, Exception):
            raise value
        return value


def _deployment(name: str, *, weight: int = 1, enabled: bool = True) -> ModelDeployment:
    return ModelDeployment(
        id=uuid4(),
        model_id=MODEL_ID,
        name=name,
        provider=ProviderName.OPENAI,
        upstream_model=f"upstream-{name}",
        weight=weight,
        enabled=enabled,
        created_at=NOW,
    )


async def _repo(*deployments: ModelDeployment) -> InMemoryModelDeploymentRepository:
    repo = InMemoryModelDeploymentRepository()
    for deployment in deployments:
        await repo.create_deployment(deployment)
    return repo


def _model() -> ModelConfig:
    return ModelConfig(
        id=MODEL_ID,
        provider=ProviderName.OPENAI,
        upstream_model="upstream-primary",
        created_at=NOW,
    )


def _request() -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(
        {"model": MODEL_ID, "messages": [{"role": "user", "content": "hi"}]}
    )


async def _router(
    repo: InMemoryModelDeploymentRepository,
    providers: dict[str, StubProvider | Exception],
    *,
    clock: FrozenClock | None = None,
    health: DeploymentHealth | None = None,
) -> ModelRouter:
    return ModelRouter(
        deployments=repo,
        pool=FakePool(providers),  # pyright: ignore[reportArgumentType]
        health=health or DeploymentHealth(threshold=2, cooldown_seconds=30),
        clock=clock or FrozenClock(),
        rng=ZeroRandom(),
        max_attempts=3,
    )


def test_weighted_order_keeps_every_deployment() -> None:
    deployments = [_deployment("a", weight=1), _deployment("b", weight=5)]

    ordered = weighted_order(deployments, ZeroRandom())

    assert len(ordered) == 2
    assert {item.name for item in ordered} == {"a", "b"}


async def test_retryable_failure_falls_over_to_the_next_deployment() -> None:
    repo = await _repo(_deployment("a"), _deployment("b"))
    primary = StubProvider(error=ProviderUpstreamError(status_code=500, message="boom"))
    backup = StubProvider(text="from-b")
    router = await _router(repo, {"a": primary, "b": backup})

    result = await router.complete(model=_model(), request=_request())

    assert result.response.choices[0].message.content == "from-b"
    assert result.deployment.name == "b"
    assert result.deployment.fallback is True
    assert result.deployment.attempts == 2
    assert primary.complete_calls == 1
    assert backup.complete_calls == 1


async def test_client_error_does_not_fail_over() -> None:
    repo = await _repo(_deployment("a"), _deployment("b"))
    primary = StubProvider(error=ProviderUpstreamError(status_code=400, message="bad"))
    backup = StubProvider()
    router = await _router(repo, {"a": primary, "b": backup})

    with pytest.raises(ProviderUpstreamError):
        await router.complete(model=_model(), request=_request())

    assert backup.complete_calls == 0


async def test_all_deployments_failing_surfaces_the_last_error() -> None:
    repo = await _repo(_deployment("a"), _deployment("b"))
    primary = StubProvider(error=ProviderUpstreamError(status_code=500, message="a"))
    backup = StubProvider(error=ProviderUpstreamError(status_code=503, message="b"))
    router = await _router(repo, {"a": primary, "b": backup})

    with pytest.raises(ProviderUpstreamError):
        await router.complete(model=_model(), request=_request())

    assert primary.complete_calls == 1
    assert backup.complete_calls == 1


async def test_failures_put_a_deployment_into_cooldown() -> None:
    repo = await _repo(_deployment("a"), _deployment("b"))
    primary = StubProvider(error=ProviderUpstreamError(status_code=500, message="boom"))
    backup = StubProvider()
    clock = FrozenClock()
    health = DeploymentHealth(threshold=2, cooldown_seconds=30)
    router = await _router(repo, {"a": primary, "b": backup}, clock=clock, health=health)

    await router.complete(model=_model(), request=_request())
    await router.complete(model=_model(), request=_request())
    await router.complete(model=_model(), request=_request())

    assert primary.complete_calls == 2
    assert backup.complete_calls == 3
    deployment_a = (await repo.list_deployments(MODEL_ID))[0]
    assert health.available(deployment_a.id, clock.now()) is False

    clock.advance(31)
    assert health.available(deployment_a.id, clock.now()) is True


async def test_missing_credentials_skip_to_the_next_deployment() -> None:
    repo = await _repo(_deployment("a"), _deployment("b"))
    backup = StubProvider(text="from-b")
    router = await _router(
        repo,
        {"a": DeploymentCredentialError("a", "OPENAI_KEY_A"), "b": backup},
    )

    result = await router.complete(model=_model(), request=_request())

    assert result.deployment.name == "b"
    assert backup.complete_calls == 1


async def test_disabled_deployments_are_not_used() -> None:
    repo = await _repo(_deployment("a", enabled=False), _deployment("b"))
    disabled = StubProvider()
    backup = StubProvider()
    router = await _router(repo, {"a": disabled, "b": backup})

    result = await router.complete(model=_model(), request=_request())

    assert result.deployment.name == "b"
    assert disabled.complete_calls == 0


async def test_stream_failure_before_first_chunk_fails_over() -> None:
    repo = await _repo(_deployment("a"), _deployment("b"))
    primary = StubProvider(
        stream_error=ProviderResponseError("Upstream provider returned an empty stream")
    )
    backup = StubProvider(text="stream-b")
    router = await _router(repo, {"a": primary, "b": backup})

    route = await router.open_stream(model=_model(), request=_request())

    assert route.deployment.name == "b"
    assert route.deployment.fallback is True
    assert route.first_chunk.choices[0].delta.content == "stream-b"
    assert primary.stream_calls == 1
    await route.upstream.aclose()


async def test_model_without_deployments_uses_the_legacy_route() -> None:
    repo = await _repo()
    legacy = StubProvider(text="legacy")
    router = await _router(repo, {"default": legacy})

    result = await router.complete(model=_model(), request=_request())

    assert result.deployment.name == "default"
    assert result.deployment.fallback is False
    assert legacy.complete_calls == 1


async def test_no_enabled_deployment_is_a_stable_503() -> None:
    repo = await _repo(_deployment("a", enabled=False))
    router = await _router(repo, {"a": StubProvider()})

    with pytest.raises(ApiError) as info:
        await router.complete(model=_model(), request=_request())

    assert info.value.status_code == 503
    assert info.value.code is ApiErrorCode.NO_DEPLOYMENT


async def test_deployment_admin_api_and_audit(
    settings: Settings,
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    configured = settings.model_copy(update={"fake_provider_enabled": True})
    container = build_container(configured)
    master = settings.master_key.get_secret_value()
    headers = {"Authorization": f"Bearer {master}"}

    async with make_client(configured, container) as client:
        created_model = await client.post(
            "/api/v1/models",
            headers=headers,
            json={"id": MODEL_ID, "provider": "fake", "upstream_model": "upstream"},
        )
        assert created_model.status_code == 201

        created = await client.post(
            f"/api/v1/models/{MODEL_ID}/deployments",
            headers=headers,
            json={
                "name": "primary",
                "provider": "fake",
                "upstream_model": "upstream-a",
                "weight": 5,
                "credential_env": "LOADTEST_KEY_A",
                "base_url": "http://127.0.0.1:9999/v1",
            },
        )
        duplicate = await client.post(
            f"/api/v1/models/{MODEL_ID}/deployments",
            headers=headers,
            json={
                "name": "primary",
                "provider": "fake",
                "upstream_model": "upstream-a",
            },
        )
        listed = await client.get(f"/api/v1/models/{MODEL_ID}/deployments", headers=headers)
        deployment_id = created.json()["id"]
        updated = await client.patch(
            f"/api/v1/deployments/{deployment_id}",
            headers=headers,
            json={"weight": 2, "enabled": False, "credential_env": None},
        )
        audit = await client.get(
            "/api/v1/admin-audit?action=model_deployment.updated", headers=headers
        )
        deleted = await client.delete(f"/api/v1/deployments/{deployment_id}", headers=headers)

    assert created.status_code == 201
    assert created.json()["credential_env"] == "LOADTEST_KEY_A"
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_deployment"
    assert [item["name"] for item in listed.json()["items"]] == ["primary"]
    assert updated.status_code == 200
    assert updated.json()["weight"] == 2
    assert updated.json()["enabled"] is False
    assert updated.json()["credential_env"] is None
    assert audit.status_code == 200
    assert audit.json()["items"][0]["action"] == "model_deployment.updated"
    assert deleted.status_code == 204
