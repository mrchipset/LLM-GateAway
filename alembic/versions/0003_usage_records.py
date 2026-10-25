"""usage records

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("api_key_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_usage_records_tenant_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"],
            ["api_keys.id"],
            name="fk_usage_records_api_key_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_usage_records_request_id", "usage_records", ["request_id"])
    op.create_index(
        "ix_usage_records_tenant_created",
        "usage_records",
        ["tenant_id", "created_at"],
    )
    op.create_index("ix_usage_records_api_key_id", "usage_records", ["api_key_id"])
    op.create_index(
        "ix_usage_records_model_created",
        "usage_records",
        ["model_id", "created_at"],
    )
    op.create_index("ix_usage_records_created_at", "usage_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_usage_records_created_at", table_name="usage_records")
    op.drop_index("ix_usage_records_model_created", table_name="usage_records")
    op.drop_index("ix_usage_records_api_key_id", table_name="usage_records")
    op.drop_index("ix_usage_records_tenant_created", table_name="usage_records")
    op.drop_index("ix_usage_records_request_id", table_name="usage_records")
    op.drop_table("usage_records")
