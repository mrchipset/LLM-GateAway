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

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    master_key: SecretStr = Field(min_length=16)
    storage_backend: StorageBackend = StorageBackend.MEMORY
    database_url: str | None = None
    redis_url: str | None = None
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    fake_provider_enabled: bool = False
    request_timeout_seconds: float = Field(default=60.0, gt=0)
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError(f"unknown log level: {value}")
        return normalized

    @model_validator(mode="after")
    def _validate_environment(self) -> Self:
        if self.storage_backend is StorageBackend.POSTGRES and not self.database_url:
            raise ValueError("database_url is required when storage_backend is postgres")

        if self.environment is Environment.PRODUCTION:
            if self.storage_backend is not StorageBackend.POSTGRES:
                raise ValueError("production requires storage_backend=postgres")
            if self.fake_provider_enabled:
                raise ValueError("production does not allow fake_provider_enabled")

        return self
