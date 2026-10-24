from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from llm_gateway.providers.base import ProviderName
from llm_gateway.storage.memory import InMemoryApiKeyRepository, InMemoryModelRepository
from llm_gateway.storage.repositories import (
    ApiKeyRecord,
    DuplicateApiKeyError,
    DuplicateModelError,
    ModelConfig,
)

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _model(index: int) -> ModelConfig:
    return ModelConfig(
        id=f"model-{index}",
        provider=ProviderName.FAKE,
        upstream_model=f"upstream-{index}",
        created_at=BASE + timedelta(seconds=index),
    )


def _key(index: int, *, key_hash: str | None = None) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=uuid4(),
        name=f"key-{index}",
        key_hash=key_hash if key_hash is not None else _hash(f"key-{index}"),
        key_prefix=f"sk-gw-{index:06d}",
        created_at=BASE + timedelta(seconds=index),
    )


async def test_model_create_get_list_delete() -> None:
    repository = InMemoryModelRepository()
    model = _model(1)

    created = await repository.create_model(model)

    assert created == model
    assert await repository.get_model(model.id) == model
    items, total = await repository.list_models(limit=10, offset=0)
    assert list(items) == [model]
    assert total == 1

    assert await repository.delete_model(model.id) is True
    assert await repository.get_model(model.id) is None
    assert await repository.delete_model(model.id) is False


async def test_model_duplicate_create_raises() -> None:
    repository = InMemoryModelRepository()
    model = _model(1)
    await repository.create_model(model)

    with pytest.raises(DuplicateModelError, match="model 'model-1' already exists"):
        await repository.create_model(model)


async def test_model_list_is_newest_first_with_pagination() -> None:
    repository = InMemoryModelRepository()
    for index in range(5):
        await repository.create_model(_model(index))

    items, total = await repository.list_models(limit=2, offset=1)

    assert total == 5
    assert [item.id for item in items] == ["model-3", "model-2"]


@pytest.mark.parametrize(
    ("limit", "offset", "message"),
    [(0, 0, "limit must be >= 1"), (-1, 0, "limit must be >= 1"), (1, -1, "offset must be >= 0")],
)
async def test_model_list_rejects_invalid_pagination(limit: int, offset: int, message: str) -> None:
    repository = InMemoryModelRepository()

    with pytest.raises(ValueError, match=message):
        await repository.list_models(limit=limit, offset=offset)


async def test_api_key_create_and_get_by_id_and_hash() -> None:
    repository = InMemoryApiKeyRepository()
    key = _key(1)

    created = await repository.create_key(key)

    assert created == key
    assert await repository.get_key(key.id) == key
    assert await repository.get_key_by_hash(key.key_hash) == key
    assert await repository.get_key(uuid4()) is None
    assert await repository.get_key_by_hash("missing-hash") is None


async def test_api_key_duplicate_hash_raises() -> None:
    repository = InMemoryApiKeyRepository()
    shared_hash = _hash("shared")
    await repository.create_key(_key(1, key_hash=shared_hash))

    with pytest.raises(DuplicateApiKeyError):
        await repository.create_key(_key(2, key_hash=shared_hash))


async def test_api_key_revoke_transitions_once() -> None:
    repository = InMemoryApiKeyRepository()
    key = _key(1)
    await repository.create_key(key)

    assert await repository.revoke_key(key.id, BASE) is True
    revoked = await repository.get_key(key.id)
    assert revoked is not None
    assert revoked.revoked_at == BASE
    assert await repository.revoke_key(key.id, BASE) is False


async def test_api_key_touch_last_used_updates_record() -> None:
    repository = InMemoryApiKeyRepository()
    key = _key(1)
    await repository.create_key(key)

    await repository.touch_last_used(key.id, BASE)

    updated = await repository.get_key(key.id)
    assert updated is not None
    assert updated.last_used_at == BASE


async def test_api_key_touch_last_used_raises_for_missing_key() -> None:
    repository = InMemoryApiKeyRepository()

    with pytest.raises(KeyError):
        await repository.touch_last_used(uuid4(), BASE)


async def test_api_key_list_is_newest_first_with_pagination() -> None:
    repository = InMemoryApiKeyRepository()
    for index in range(5):
        await repository.create_key(_key(index))

    items, total = await repository.list_keys(limit=2, offset=1)

    assert total == 5
    assert [item.name for item in items] == ["key-3", "key-2"]


async def test_model_list_enabled_only_filters_before_pagination() -> None:
    repository = InMemoryModelRepository()
    await repository.create_model(_model(0))
    await repository.create_model(_model(1))
    await repository.create_model(
        ModelConfig(
            id="model-disabled",
            provider=ProviderName.FAKE,
            upstream_model="upstream-disabled",
            created_at=BASE + timedelta(seconds=2),
            enabled=False,
        )
    )

    items, total = await repository.list_models(limit=10, offset=0, enabled_only=True)

    assert total == 2
    assert {item.id for item in items} == {"model-0", "model-1"}

    page, filtered_total = await repository.list_models(limit=1, offset=0, enabled_only=True)

    assert filtered_total == 2
    assert [item.id for item in page] == ["model-1"]


def test_model_rejects_naive_created_at() -> None:
    with pytest.raises(ValueError, match="created_at"):
        ModelConfig(
            id="model-1",
            provider=ProviderName.FAKE,
            upstream_model="upstream-1",
            created_at=datetime(2026, 1, 1, 12, 0),  # noqa: DTZ001 - naive input under test
        )


def test_model_rejects_blank_id() -> None:
    with pytest.raises(ValueError, match="id"):
        ModelConfig(
            id="   ",
            provider=ProviderName.FAKE,
            upstream_model="upstream-1",
            created_at=BASE,
        )


def test_api_key_rejects_naive_expires_at() -> None:
    with pytest.raises(ValueError, match="expires_at"):
        ApiKeyRecord(
            id=uuid4(),
            name="key-1",
            key_hash=_hash("key-1"),
            key_prefix="sk-gw-000001",
            created_at=BASE,
            expires_at=datetime(2026, 1, 2, 12, 0),  # noqa: DTZ001 - naive input under test
        )


def test_api_key_rejects_naive_last_used_at() -> None:
    with pytest.raises(ValueError, match="last_used_at"):
        ApiKeyRecord(
            id=uuid4(),
            name="key-1",
            key_hash=_hash("key-1"),
            key_prefix="sk-gw-000001",
            created_at=BASE,
            last_used_at=datetime(2026, 1, 2, 12, 0),  # noqa: DTZ001 - naive input under test
        )


def test_api_key_rejects_invalid_hash() -> None:
    with pytest.raises(ValueError, match="key_hash"):
        _key(1, key_hash="not-a-hash")
