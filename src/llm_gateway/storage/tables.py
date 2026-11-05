from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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
    model_access_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'all'"),
    )
    plan_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_allow_overage: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    monthly_cost_budget: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )
    audit_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_per_minute: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_concurrent_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
        CheckConstraint(
            "model_access_mode IN ('all', 'allowlist')",
            name="ck_tenants_model_access_mode",
        ),
        CheckConstraint(
            "plan_tokens IS NULL OR plan_tokens >= 1",
            name="ck_tenants_plan_tokens_positive",
        ),
        CheckConstraint(
            "monthly_cost_budget IS NULL OR monthly_cost_budget >= 0",
            name="ck_tenants_monthly_cost_budget_non_negative",
        ),
        CheckConstraint(
            "audit_retention_days IS NULL OR audit_retention_days >= 0",
            name="ck_tenants_audit_retention_days_non_negative",
        ),
        CheckConstraint(
            "tokens_per_minute IS NULL OR tokens_per_minute >= 1",
            name="ck_tenants_tokens_per_minute_positive",
        ),
        CheckConstraint(
            "max_concurrent_requests IS NULL OR max_concurrent_requests >= 1",
            name="ck_tenants_max_concurrent_requests_positive",
        ),
    )


class TenantModelAccessRow(Base):
    """Composite key of (tenant, model) plus a CASCADE from both sides."""

    __tablename__ = "tenant_model_access"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "tenants.id",
            name="fk_tenant_model_access_tenant_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    model_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey(
            "models.id",
            name="fk_tenant_model_access_model_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
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
    requests_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_per_minute: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_concurrent_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_api_keys_key_hash", "key_hash", unique=True),
        Index("ix_api_keys_tenant_id", "tenant_id"),
        CheckConstraint(
            "requests_per_minute IS NULL OR requests_per_minute >= 1",
            name="ck_api_keys_requests_per_minute_positive",
        ),
        CheckConstraint(
            "tokens_per_minute IS NULL OR tokens_per_minute >= 1",
            name="ck_api_keys_tokens_per_minute_positive",
        ),
        CheckConstraint(
            "max_concurrent_requests IS NULL OR max_concurrent_requests >= 1",
            name="ck_api_keys_max_concurrent_requests_positive",
        ),
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
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_requests_session_turn", "session_id", "turn_index"),
        Index("ix_audit_requests_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_requests_parent_request_id", "parent_request_id"),
        Index("ix_audit_requests_api_key_created", "api_key_id", "created_at"),
        Index("ix_audit_requests_trace_id", "trace_id"),
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
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    covered_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    billable_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    list_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    billed_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_usage_records_request_id", "request_id"),
        Index("ix_usage_records_tenant_created", "tenant_id", "created_at"),
        Index("ix_usage_records_api_key_id", "api_key_id"),
        Index("ix_usage_records_model_created", "model_id", "created_at"),
        Index("ix_usage_records_created_at", "created_at"),
        Index("ix_usage_records_trace_id", "trace_id"),
    )


class TenantMonthUsageRow(Base):
    """O(1) monthly rollup, updated in the same transaction as ``usage_records``."""

    __tablename__ = "tenant_month_usage"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "tenants.id",
            name="fk_tenant_month_usage_tenant_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    period_start: Mapped[date] = mapped_column(Date, primary_key=True)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    cached_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    covered_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    billable_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    list_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, server_default=text("0")
    )
    billed_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, server_default=text("0")
    )
    requests: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelRow(Base):
    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    upstream_model: Mapped[str] = mapped_column(String(256), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requests_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_per_minute: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supports_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    supports_streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())

    __table_args__ = (
        CheckConstraint(
            "requests_per_minute IS NULL OR requests_per_minute >= 1",
            name="ck_models_requests_per_minute_positive",
        ),
        CheckConstraint(
            "tokens_per_minute IS NULL OR tokens_per_minute >= 1",
            name="ck_models_tokens_per_minute_positive",
        ),
        CheckConstraint(
            "context_window IS NULL OR context_window >= 1",
            name="ck_models_context_window_positive",
        ),
        CheckConstraint(
            "max_output_tokens IS NULL OR max_output_tokens >= 1",
            name="ck_models_max_output_tokens_positive",
        ),
    )


class ModelPriceRow(Base):
    """Versioned price list; the effective row is the newest ``effective_from <= now``."""

    __tablename__ = "model_prices"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    model_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey(
            "models.id",
            name="fk_model_prices_model_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    input_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    cached_input_per_million: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )
    output_per_million: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "ix_model_prices_model_effective",
            "model_id",
            "effective_from",
            unique=True,
        ),
        CheckConstraint(
            "input_per_million >= 0 AND output_per_million >= 0",
            name="ck_model_prices_non_negative",
        ),
        CheckConstraint(
            "cached_input_per_million IS NULL OR cached_input_per_million >= 0",
            name="ck_model_prices_cached_non_negative",
        ),
    )


class AdminUserRow(Base):
    __tablename__ = "admin_users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_admin_users_username", "username", unique=True),
        CheckConstraint(
            "role IN ('owner', 'operator', 'auditor')",
            name="ck_admin_users_role",
        ),
    )


class AdminSessionRow(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    admin_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "admin_users.id",
            name="fk_admin_sessions_admin_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_admin_sessions_token_hash", "token_hash", unique=True),
        Index("ix_admin_sessions_admin_id", "admin_id"),
    )


class AdminAuditRow(Base):
    __tablename__ = "admin_audit_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_admin_audit_created", "created_at"),
        Index("ix_admin_audit_actor_created", "actor_id", "created_at"),
        Index("ix_admin_audit_target", "target_type", "target_id"),
        CheckConstraint(
            "actor_type IN ('admin', 'master', 'bootstrap')",
            name="ck_admin_audit_actor_type",
        ),
    )


class AdminLoginAttemptRow(Base):
    __tablename__ = "admin_login_attempts"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)


class ModelDeploymentRow(Base):
    __tablename__ = "model_deployments"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    model_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey(
            "models.id",
            name="fk_model_deployments_model_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    upstream_model: Mapped[str] = mapped_column(String(256), nullable=False)
    credential_env: Mapped[str | None] = mapped_column(String(100), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_model_deployments_model_name",
            "model_id",
            "name",
            unique=True,
        ),
        Index("ix_model_deployments_model", "model_id", "enabled"),
        CheckConstraint(
            "weight >= 1 AND weight <= 100",
            name="ck_model_deployments_weight",
        ),
    )
