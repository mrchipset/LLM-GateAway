from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    false,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    audit_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())

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


class AuditSessionRow(Base):
    __tablename__ = "audit_sessions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "tenants.id",
            name="fk_audit_sessions_tenant_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    external_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    api_key_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "api_keys.id",
            name="fk_audit_sessions_api_key_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    api_key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    root_request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    title_preview: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_audit_sessions_tenant_last_seen", "tenant_id", "last_seen_at"),
        Index("ix_audit_sessions_tenant_created", "tenant_id", "created_at"),
        Index(
            "uq_audit_sessions_tenant_external",
            "tenant_id",
            "external_session_id",
            unique=True,
            postgresql_where=text("external_session_id IS NOT NULL"),
        ),
    )


class AuditRequestRow(Base):
    __tablename__ = "audit_requests"

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "audit_sessions.id",
            name="fk_audit_requests_session_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    parent_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "tenants.id",
            name="fk_audit_requests_tenant_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    api_key_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "api_keys.id",
            name="fk_audit_requests_api_key_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    match_method: Mapped[str] = mapped_column(String(16), nullable=False)
    change_type: Mapped[str] = mapped_column(String(24), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    is_stream: Mapped[bool] = mapped_column(Boolean, nullable=False)
    request_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    message_hashes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    request_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    response_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    response_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_requests_session_turn", "session_id", "turn_index"),
        Index("ix_audit_requests_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_requests_parent_request_id", "parent_request_id"),
        Index("ix_audit_requests_api_key_created", "api_key_id", "created_at"),
    )


class AuditTurnDiffRow(Base):
    __tablename__ = "audit_turn_diffs"

    request_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "audit_requests.request_id",
            name="fk_audit_turn_diffs_request_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    previous_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    change_type: Mapped[str] = mapped_column(String(24), nullable=False)
    common_prefix: Mapped[int] = mapped_column(Integer, nullable=False)
    added_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    modified_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    removed_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    parameter_changes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    usage_delta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    response_change: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
