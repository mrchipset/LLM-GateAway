from __future__ import annotations

from typing import Any

import pytest

from llm_gateway.config import Environment, Settings, StorageBackend
from llm_gateway.storage import db as db_module
from llm_gateway.storage.db import Database

DATABASE_URL = "postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway"


def _settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": Environment.TEST,
        "master_key": "test-master-key-0123456789abcdef",
        "storage_backend": StorageBackend.POSTGRES,
        "database_url": DATABASE_URL,
    }
    values.update(overrides)
    return Settings(**values)


def test_engine_uses_the_configured_pool_and_statement_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_engine(url: str, **kwargs: Any) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(db_module, "create_async_engine", fake_engine)

    Database.from_settings(
        _settings(
            database_pool_size=20,
            database_max_overflow=0,
            database_pool_timeout_seconds=2.5,
            database_statement_timeout_ms=1500,
        )
    )

    assert captured["url"] == DATABASE_URL
    assert captured["pool_size"] == 20
    assert captured["max_overflow"] == 0
    assert captured["pool_timeout"] == 2.5
    assert captured["connect_args"] == {
        "timeout": 10.0,
        "server_settings": {"statement_timeout": "1500ms"},
    }


def test_zero_statement_timeout_leaves_the_server_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_engine(url: str, **kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(db_module, "create_async_engine", fake_engine)

    Database.from_settings(_settings(database_statement_timeout_ms=0))

    assert captured["connect_args"] == {"timeout": 10.0}
