"""monthly tenant usage rollup

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ZERO = sa.text("0")


def upgrade() -> None:
    op.create_table(
        "tenant_month_usage",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=False, server_default=_ZERO),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=False, server_default=_ZERO),
        sa.Column("cached_tokens", sa.BigInteger(), nullable=False, server_default=_ZERO),
        sa.Column("total_tokens", sa.BigInteger(), nullable=False, server_default=_ZERO),
        sa.Column("covered_tokens", sa.BigInteger(), nullable=False, server_default=_ZERO),
        sa.Column("billable_tokens", sa.BigInteger(), nullable=False, server_default=_ZERO),
        sa.Column(
            "list_cost",
            sa.Numeric(18, 6),
            nullable=False,
            server_default=_ZERO,
        ),
        sa.Column(
            "billed_cost",
            sa.Numeric(18, 6),
            nullable=False,
            server_default=_ZERO,
        ),
        sa.Column("requests", sa.BigInteger(), nullable=False, server_default=_ZERO),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_month_usage_tenant_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "period_start"),
    )

    # Existing detail rows are the source of truth at upgrade time.
    op.execute(
        sa.text(
            """
            INSERT INTO tenant_month_usage (
                tenant_id, period_start, prompt_tokens, completion_tokens,
                cached_tokens, total_tokens, covered_tokens, billable_tokens,
                list_cost, billed_cost, requests, updated_at
            )
            SELECT
                tenant_id,
                date_trunc('month', created_at)::date,
                COALESCE(SUM(prompt_tokens), 0),
                COALESCE(SUM(completion_tokens), 0),
                COALESCE(SUM(cached_tokens), 0),
                COALESCE(SUM(total_tokens), 0),
                COALESCE(SUM(covered_tokens), 0),
                COALESCE(SUM(billable_tokens), 0),
                COALESCE(SUM(list_cost), 0),
                COALESCE(SUM(billed_cost), 0),
                COUNT(*),
                now()
            FROM usage_records
            GROUP BY tenant_id, date_trunc('month', created_at)::date
            """
        )
    )


def downgrade() -> None:
    op.drop_table("tenant_month_usage")
