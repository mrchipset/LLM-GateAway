from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    monthly_token_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requests_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_tenants_name", "name", unique=True),
        CheckConstraint(
            "monthly_token_quota IS NULL OR monthly_token_quota >= 1",
            name="ck_tenants_monthly_token_quota_positive",
        ),
        CheckConstraint(
            "requests_per_minute IS NULL OR requests_per_minute >= 1",
            name="ck_tenants_requests_per_minute_positive",
        ),
    )


class TenantRateLimitRow(Base):
    __tablename__ = "tenant_rate_limits"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "tenants.id",
            name="fk_tenant_rate_limits_tenant_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)


class ApiKeyRow(Base):
    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_api_keys_key_hash", "key_hash", unique=True),
        Index("ix_api_keys_tenant_id", "tenant_id"),
    )


class UsageRow(Base):
    __tablename__ = "usage_records"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "tenants.id",
            name="fk_usage_records_tenant_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    api_key_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "api_keys.id",
            name="fk_usage_records_api_key_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_usage_records_request_id", "request_id"),
        Index("ix_usage_records_tenant_created", "tenant_id", "created_at"),
        Index("ix_usage_records_api_key_id", "api_key_id"),
        Index("ix_usage_records_model_created", "model_id", "created_at"),
        Index("ix_usage_records_created_at", "created_at"),
    )


class ModelRow(Base):
    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    upstream_model: Mapped[str] = mapped_column(String(256), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
