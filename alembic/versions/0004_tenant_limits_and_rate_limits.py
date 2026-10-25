"""tenant limits and rate limits

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("monthly_token_quota", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("requests_per_minute", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_tenants_monthly_token_quota_positive",
        "tenants",
        "monthly_token_quota IS NULL OR monthly_token_quota >= 1",
    )
    op.create_check_constraint(
        "ck_tenants_requests_per_minute_positive",
        "tenants",
        "requests_per_minute IS NULL OR requests_per_minute >= 1",
    )

    op.create_table(
        "tenant_rate_limits",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_rate_limits_tenant_id",
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("tenant_rate_limits")
    op.drop_constraint(
        "ck_tenants_requests_per_minute_positive",
        "tenants",
        type_="check",
    )
    op.drop_constraint(
        "ck_tenants_monthly_token_quota_positive",
        "tenants",
        type_="check",
    )
    op.drop_column("tenants", "requests_per_minute")
    op.drop_column("tenants", "monthly_token_quota")
