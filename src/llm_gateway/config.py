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
    tracing_enabled: bool = False
    tracing_endpoint: str | None = None
    tracing_sample_ratio: float = Field(default=0.1, ge=0, le=1)
    tracing_service_name: str = "llm-gateway"
    tracing_export_timeout_seconds: float = Field(default=5.0, gt=0)
    metrics_enabled: bool = False
    metrics_host: str = "127.0.0.1"
    metrics_port: int = Field(default=9464, ge=1, le=65535)
    metrics_service_name: str = "llm-gateway"
    billing_currency: str = "USD"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError(f"unknown log level: {value}")
        return normalized

    @field_validator("billing_currency")
    @classmethod
    def _validate_billing_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("billing_currency must be a 3-letter currency code")
        return normalized

    @field_validator("tracing_endpoint")
    @classmethod
    def _validate_tracing_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("tracing_endpoint must be an http(s) URL")
        return normalized

    @model_validator(mode="after")
    def _validate_environment(self) -> Self:
        secret = self.master_key.get_secret_value()
        normalized_secret = secret.lower()
        if "change-me" in normalized_secret or "changeme" in normalized_secret:
            raise ValueError("master_key must not contain a placeholder value")

        if self.tracing_enabled and self.tracing_endpoint is None:
            raise ValueError("tracing_endpoint is required when tracing_enabled is true")

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
