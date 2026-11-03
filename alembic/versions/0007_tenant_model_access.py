"""tenant scoped model access

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "model_access_mode",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'all'"),
        ),
    )
    op.create_check_constraint(
        "ck_tenants_model_access_mode",
        "tenants",
        "model_access_mode IN ('all', 'allowlist')",
    )

    op.create_table(
        "tenant_model_access",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_model_access_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["models.id"],
            name="fk_tenant_model_access_model_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "model_id"),
    )


def downgrade() -> None:
    op.drop_table("tenant_model_access")
    op.drop_constraint("ck_tenants_model_access_mode", "tenants", type_="check")
    op.drop_column("tenants", "model_access_mode")
