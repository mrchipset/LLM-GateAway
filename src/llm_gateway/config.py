from __future__ import annotations

import logging
from enum import StrEnum
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class StorageBackend(StrEnum):
    MEMORY = "memory"
    POSTGRES = "postgres"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    environment: Environment
    log_level: str = "INFO"
    master_key: SecretStr = Field(min_length=16)
    storage_backend: StorageBackend = StorageBackend.MEMORY
    database_url: str | None = None
    redis_url: str | None = None
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    fake_provider_enabled: bool = False
    request_timeout_seconds: float = Field(default=60.0, gt=0)
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)
    audit_enabled: bool = False
    audit_max_content_bytes: int = Field(default=262144, ge=1024)
    audit_write_timeout_seconds: float = Field(default=2.0, gt=0)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError(f"unknown log level: {value}")
        return normalized

    @model_validator(mode="after")
    def _validate_environment(self) -> Self:
        secret = self.master_key.get_secret_value()
        normalized_secret = secret.lower()
        if "change-me" in normalized_secret or "changeme" in normalized_secret:
            raise ValueError("master_key must not contain a placeholder value")

        if self.storage_backend is StorageBackend.POSTGRES and not self.database_url:
            raise ValueError("database_url is required when storage_backend is postgres")

        if self.environment is Environment.PRODUCTION:
            if len(secret) < 32:
                raise ValueError("production master_key must be at least 32 characters")
            if self.storage_backend is not StorageBackend.POSTGRES:
                raise ValueError("production requires storage_backend=postgres")
            if self.fake_provider_enabled:
                raise ValueError("production does not allow fake_provider_enabled")

        return self
