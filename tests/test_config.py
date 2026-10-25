from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest
from pydantic import ValidationError

from llm_gateway.config import Environment, Settings, StorageBackend

MASTER_KEY = "test-master-key-0123456789abcdef"


def _load_settings_without_env_file() -> Settings:
    loader = cast(Callable[..., Settings], Settings)
    return loader(_env_file=None)


def test_missing_environment_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_MASTER_KEY", MASTER_KEY)
    monkeypatch.delenv("GATEWAY_ENVIRONMENT", raising=False)

    with pytest.raises(ValidationError):
        _load_settings_without_env_file()


def test_missing_master_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_ENVIRONMENT", "test")
    monkeypatch.delenv("GATEWAY_MASTER_KEY", raising=False)

    with pytest.raises(ValidationError):
        _load_settings_without_env_file()


def test_too_short_master_key_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "environment": Environment.TEST,
                "master_key": "short",
            }
        )


def test_placeholder_master_key_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "environment": Environment.DEVELOPMENT,
                "master_key": "change-me-to-a-long-random-string",
            }
        )


def test_production_short_master_key_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "environment": Environment.PRODUCTION,
                "storage_backend": StorageBackend.POSTGRES,
                "database_url": "postgresql+asyncpg://gateway:gateway@localhost/gateway",
                "master_key": "x" * 20,
            }
        )


def test_postgres_backend_without_database_url_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "environment": Environment.TEST,
                "master_key": MASTER_KEY,
                "storage_backend": StorageBackend.POSTGRES,
            }
        )


def test_production_with_memory_backend_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "environment": Environment.PRODUCTION,
                "master_key": MASTER_KEY,
                "storage_backend": StorageBackend.MEMORY,
            }
        )


def test_production_with_fake_provider_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "environment": Environment.PRODUCTION,
                "master_key": MASTER_KEY,
                "storage_backend": StorageBackend.POSTGRES,
                "database_url": "postgresql+asyncpg://gateway:gateway@localhost/gateway",
                "fake_provider_enabled": True,
            }
        )


def test_valid_development_settings_load() -> None:
    settings = Settings(
        **{
            "_env_file": None,
            "environment": Environment.DEVELOPMENT,
            "master_key": MASTER_KEY,
        }
    )

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.storage_backend is StorageBackend.MEMORY
    assert settings.log_level == "INFO"
    assert settings.request_timeout_seconds > 0
    assert settings.connect_timeout_seconds > 0
    assert 0 <= settings.max_retries <= 5
    assert settings.openai_base_url
    assert settings.deepseek_api_key is None
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.fake_provider_enabled is False


def test_settings_load_from_gateway_env_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GATEWAY_ENVIRONMENT", "development")
    monkeypatch.setenv("GATEWAY_MASTER_KEY", MASTER_KEY)

    settings = _load_settings_without_env_file()

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.master_key.get_secret_value() == MASTER_KEY


def test_deepseek_settings_load_from_gateway_env_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GATEWAY_ENVIRONMENT", "development")
    monkeypatch.setenv("GATEWAY_MASTER_KEY", MASTER_KEY)
    monkeypatch.setenv("GATEWAY_DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setenv("GATEWAY_DEEPSEEK_BASE_URL", "https://deepseek.test")

    settings = _load_settings_without_env_file()

    assert settings.deepseek_api_key is not None
    assert settings.deepseek_api_key.get_secret_value() == "sk-deepseek-test"
    assert settings.deepseek_base_url == "https://deepseek.test"


def test_log_level_is_normalized_to_upper_case() -> None:
    settings = Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
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
                "environment": Environment.TEST,
                "master_key": MASTER_KEY,
                "log_level": "verbose",
            }
        )


def test_non_positive_timeout_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "environment": Environment.TEST,
                "master_key": MASTER_KEY,
                "request_timeout_seconds": 0,
            }
        )


def test_max_retries_out_of_range_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{
                "_env_file": None,
                "environment": Environment.TEST,
                "master_key": MASTER_KEY,
                "max_retries": 6,
            }
        )


def test_master_key_is_not_exposed_in_repr() -> None:
    settings = Settings(
        **{
            "_env_file": None,
            "environment": Environment.TEST,
            "master_key": MASTER_KEY,
        }
    )

    assert MASTER_KEY not in repr(settings)
