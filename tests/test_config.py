from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from llm_gateway.config import Environment, Settings, StorageBackend

MASTER_KEY = "test-master-key-0123456789abcdef"


def test_missing_master_key_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("GATEWAY_MASTER_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    load_settings = cast(Callable[[], Settings], Settings)

    with pytest.raises(ValidationError):
        load_settings()


def test_too_short_master_key_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(**{"_env_file": None, "master_key": "short"})


def test_postgres_backend_without_database_url_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "master_key": MASTER_KEY,
                "storage_backend": StorageBackend.POSTGRES,
            }
        )


def test_production_with_memory_backend_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "master_key": MASTER_KEY,
                "environment": Environment.PRODUCTION,
                "storage_backend": StorageBackend.MEMORY,
            }
        )


def test_production_with_fake_provider_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "master_key": MASTER_KEY,
                "environment": Environment.PRODUCTION,
                "storage_backend": StorageBackend.POSTGRES,
                "database_url": "postgresql+asyncpg://gateway:gateway@localhost/gateway",
                "fake_provider_enabled": True,
            }
        )


def test_defaults_load_for_test_environment() -> None:
    settings = Settings(
        **{
            "_env_file": None,
            "master_key": MASTER_KEY,
            "environment": Environment.TEST,
        }
    )

    assert settings.environment is Environment.TEST
    assert settings.storage_backend is StorageBackend.MEMORY
    assert settings.log_level == "INFO"
    assert settings.request_timeout_seconds == 60.0
    assert settings.connect_timeout_seconds == 10.0
    assert settings.max_retries == 2
    assert settings.openai_base_url == "https://api.openai.com/v1"
    assert settings.fake_provider_enabled is False


def test_log_level_is_normalized_to_upper_case() -> None:
    settings = Settings(
        **{
            "_env_file": None,
            "master_key": MASTER_KEY,
            "log_level": "debug",
        }
    )

    assert settings.log_level == "DEBUG"


def test_unknown_log_level_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "master_key": MASTER_KEY,
                "log_level": "verbose",
            }
        )


def test_non_positive_timeout_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "master_key": MASTER_KEY,
                "request_timeout_seconds": 0,
            }
        )


def test_max_retries_out_of_range_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "master_key": MASTER_KEY,
                "max_retries": 6,
            }
        )


def test_master_key_is_not_exposed_in_repr() -> None:
    settings = Settings(**{"_env_file": None, "master_key": MASTER_KEY})

    assert MASTER_KEY not in repr(settings)
