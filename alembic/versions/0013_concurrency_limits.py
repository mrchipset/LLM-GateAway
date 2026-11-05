"""in-flight concurrency limits for tenants and keys

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("tenants", "api_keys"):
        op.add_column(table, sa.Column("max_concurrent_requests", sa.Integer(), nullable=True))
        op.create_check_constraint(
            f"ck_{table}_max_concurrent_requests_positive",
            table,
            "max_concurrent_requests IS NULL OR max_concurrent_requests >= 1",
        )


def downgrade() -> None:
    for table in ("api_keys", "tenants"):
        op.drop_constraint(
            f"ck_{table}_max_concurrent_requests_positive",
            table,
            type_="check",
        )
        op.drop_column(table, "max_concurrent_requests")
