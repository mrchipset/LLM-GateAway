"""billing: model prices, tenant plan and cost budget

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("plan_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "plan_allow_overage",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("monthly_cost_budget", sa.Numeric(18, 6), nullable=True),
    )
    op.create_check_constraint(
        "ck_tenants_plan_tokens_positive",
        "tenants",
        "plan_tokens IS NULL OR plan_tokens >= 1",
    )
    op.create_check_constraint(
        "ck_tenants_monthly_cost_budget_non_negative",
        "tenants",
        "monthly_cost_budget IS NULL OR monthly_cost_budget >= 0",
    )

    op.add_column(
        "usage_records",
        sa.Column(
            "covered_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "usage_records",
        sa.Column(
            "billable_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "usage_records",
        sa.Column("list_cost", sa.Numeric(18, 6), nullable=True),
    )
    op.add_column(
        "usage_records",
        sa.Column("billed_cost", sa.Numeric(18, 6), nullable=True),
    )

    op.create_table(
        "model_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("input_per_million", sa.Numeric(18, 6), nullable=False),
        sa.Column("cached_input_per_million", sa.Numeric(18, 6), nullable=True),
        sa.Column("output_per_million", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["models.id"],
            name="fk_model_prices_model_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "input_per_million >= 0 AND output_per_million >= 0",
            name="ck_model_prices_non_negative",
        ),
        sa.CheckConstraint(
            "cached_input_per_million IS NULL OR cached_input_per_million >= 0",
            name="ck_model_prices_cached_non_negative",
        ),
    )
    op.create_index(
        "ix_model_prices_model_effective",
        "model_prices",
        ["model_id", "effective_from"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_model_prices_model_effective", table_name="model_prices")
    op.drop_table("model_prices")

    op.drop_column("usage_records", "billed_cost")
    op.drop_column("usage_records", "list_cost")
    op.drop_column("usage_records", "billable_tokens")
    op.drop_column("usage_records", "covered_tokens")

    op.drop_constraint(
        "ck_tenants_monthly_cost_budget_non_negative",
        "tenants",
        type_="check",
    )
    op.drop_constraint("ck_tenants_plan_tokens_positive", "tenants", type_="check")
    op.drop_column("tenants", "monthly_cost_budget")
    op.drop_column("tenants", "plan_allow_overage")
    op.drop_column("tenants", "plan_tokens")
