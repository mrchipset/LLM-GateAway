"""request audit

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "audit_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_table(
        "audit_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("external_session_id", sa.String(length=64), nullable=True),
        sa.Column("api_key_id", sa.Uuid(), nullable=False),
        sa.Column("api_key_prefix", sa.String(length=16), nullable=False),
        sa.Column("root_request_id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("title_preview", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_audit_sessions_tenant_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"],
            ["api_keys.id"],
            name="fk_audit_sessions_api_key_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_audit_sessions_tenant_last_seen",
        "audit_sessions",
        ["tenant_id", "last_seen_at"],
    )
    op.create_index(
        "ix_audit_sessions_tenant_created",
        "audit_sessions",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "uq_audit_sessions_tenant_external",
        "audit_sessions",
        ["tenant_id", "external_session_id"],
        unique=True,
        postgresql_where=sa.text("external_session_id IS NOT NULL"),
    )

    op.create_table(
        "audit_requests",
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("parent_request_id", sa.String(length=64), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("api_key_id", sa.Uuid(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("match_method", sa.String(length=16), nullable=False),
        sa.Column("change_type", sa.String(length=24), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("is_stream", sa.Boolean(), nullable=False),
        sa.Column("request_messages", postgresql.JSONB(), nullable=False),
        sa.Column("message_hashes", postgresql.JSONB(), nullable=False),
        sa.Column("request_params", postgresql.JSONB(), nullable=False),
        sa.Column("response_content", sa.Text(), nullable=True),
        sa.Column("response_tool_calls", postgresql.JSONB(), nullable=True),
        sa.Column("response_content_hash", sa.String(length=64), nullable=True),
        sa.Column("finish_reason", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "truncated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("request_id"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["audit_sessions.id"],
            name="fk_audit_requests_session_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_audit_requests_tenant_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"],
            ["api_keys.id"],
            name="fk_audit_requests_api_key_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_audit_requests_session_turn",
        "audit_requests",
        ["session_id", "turn_index"],
    )
    op.create_index(
        "ix_audit_requests_tenant_created",
        "audit_requests",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_audit_requests_parent_request_id",
        "audit_requests",
        ["parent_request_id"],
    )
    op.create_index(
        "ix_audit_requests_api_key_created",
        "audit_requests",
        ["api_key_id", "created_at"],
    )

    op.create_table(
        "audit_turn_diffs",
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("previous_request_id", sa.String(length=64), nullable=True),
        sa.Column("change_type", sa.String(length=24), nullable=False),
        sa.Column("common_prefix", sa.Integer(), nullable=False),
        sa.Column("added_messages", postgresql.JSONB(), nullable=False),
        sa.Column("modified_messages", postgresql.JSONB(), nullable=False),
        sa.Column("removed_messages", postgresql.JSONB(), nullable=False),
        sa.Column("parameter_changes", postgresql.JSONB(), nullable=False),
        sa.Column("usage_delta", postgresql.JSONB(), nullable=False),
        sa.Column("response_change", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("request_id"),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["audit_requests.request_id"],
            name="fk_audit_turn_diffs_request_id",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_turn_diffs")
    op.drop_index("ix_audit_requests_api_key_created", table_name="audit_requests")
    op.drop_index("ix_audit_requests_parent_request_id", table_name="audit_requests")
    op.drop_index("ix_audit_requests_tenant_created", table_name="audit_requests")
    op.drop_index("ix_audit_requests_session_turn", table_name="audit_requests")
    op.drop_table("audit_requests")
    op.drop_index("uq_audit_sessions_tenant_external", table_name="audit_sessions")
    op.drop_index("ix_audit_sessions_tenant_created", table_name="audit_sessions")
    op.drop_index("ix_audit_sessions_tenant_last_seen", table_name="audit_sessions")
    op.drop_table("audit_sessions")
    op.drop_column("tenants", "audit_enabled")
