"""per-tenant audit retention override

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("audit_retention_days", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_tenants_audit_retention_days_non_negative",
        "tenants",
        "audit_retention_days IS NULL OR audit_retention_days >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tenants_audit_retention_days_non_negative",
        "tenants",
        type_="check",
    )
    op.drop_column("tenants", "audit_retention_days")
