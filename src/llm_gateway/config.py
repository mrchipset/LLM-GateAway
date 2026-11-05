from __future__ import annotations

import json
import logging
import re
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


class RateLimitBackend(StrEnum):
    STORAGE = "storage"
    REDIS = "redis"


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
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=5, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    database_statement_timeout_ms: int = Field(default=30_000, ge=0, le=600_000)
    redis_url: str | None = None
    rate_limit_backend: RateLimitBackend = RateLimitBackend.STORAGE
    rate_limit_fail_open: bool = True
    rate_limit_redis_timeout_seconds: float = Field(default=0.2, ge=0.01, le=10)
    concurrency_lease_seconds: int = Field(default=600, ge=30, le=3600)
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    fake_provider_enabled: bool = False
    request_timeout_seconds: float = Field(default=60.0, gt=0)
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    stream_idle_timeout_seconds: float = Field(default=60.0, ge=0, le=3600)
    shutdown_grace_seconds: float = Field(default=30.0, ge=0, le=600)
    max_retries: int = Field(default=2, ge=0, le=5)
    audit_enabled: bool = False
    audit_max_content_bytes: int = Field(default=262144, ge=1024)
    audit_write_timeout_seconds: float = Field(default=2.0, gt=0)
    audit_retention_days: int = Field(default=90, ge=0)
    audit_redact_patterns: str = ""
    tracing_enabled: bool = False
    tracing_endpoint: str | None = None
    tracing_sample_ratio: float = Field(default=0.1, ge=0, le=1)
    tracing_service_name: str = "llm-gateway"
    tracing_export_timeout_seconds: float = Field(default=5.0, gt=0)
    metrics_enabled: bool = False
    metrics_host: str = "127.0.0.1"
    metrics_port: int = Field(default=9464, ge=1, le=65535)
    metrics_service_name: str = "llm-gateway"
    billing_enabled: bool = True
    billing_currency: str = "USD"
    max_request_bytes: int = Field(default=1_048_576, ge=1024)
    max_messages: int = Field(default=200, ge=1)
    max_prompt_chars: int = Field(default=1_000_000, ge=1)
    max_tokens_limit: int = Field(default=32_768, ge=1)
    max_tools: int = Field(default=128, ge=1)
    route_max_attempts: int = Field(default=3, ge=1, le=10)
    route_failure_threshold: int = Field(default=3, ge=1, le=100)
    route_cooldown_seconds: int = Field(default=30, ge=1, le=3600)
    session_ttl_hours: int = Field(default=12, ge=1, le=720)
    master_key_enabled: bool = True
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None

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

    @field_validator("audit_redact_patterns")
    @classmethod
    def _validate_redact_patterns(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            return ""
        try:
            rules = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise ValueError("audit_redact_patterns must be a JSON array") from exc
        if not isinstance(rules, list):
            raise ValueError("audit_redact_patterns must be a JSON array")
        seen: set[str] = set()
        for rule in rules:
            if not isinstance(rule, dict):
                raise ValueError("each redaction rule must be an object with name and pattern")
            name = rule.get("name")
            pattern = rule.get("pattern")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("redaction rule name must be a non-empty string")
            if name in seen:
                raise ValueError(f"duplicate redaction rule name: {name}")
            seen.add(name)
            if not isinstance(pattern, str) or not pattern:
                raise ValueError(f"redaction rule '{name}' must have a non-empty pattern")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"redaction rule '{name}' has an invalid pattern") from exc
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
        if self.rate_limit_backend is RateLimitBackend.REDIS and not self.redis_url:
            raise ValueError("redis_url is required when rate_limit_backend is redis")

        if self.environment is Environment.PRODUCTION:
            if len(secret) < 32:
                raise ValueError("production master_key must be at least 32 characters")
            if self.storage_backend is not StorageBackend.POSTGRES:
                raise ValueError("production requires storage_backend=postgres")
            if self.fake_provider_enabled:
                raise ValueError("production does not allow fake_provider_enabled")

        return self
