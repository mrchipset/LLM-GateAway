"""per-key and per-model rate limits, tenant token limits

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_limits(table: str, *, tokens: bool) -> None:
    op.add_column(table, sa.Column("requests_per_minute", sa.Integer(), nullable=True))
    op.create_check_constraint(
        f"ck_{table}_requests_per_minute_positive",
        table,
        "requests_per_minute IS NULL OR requests_per_minute >= 1",
    )
    if tokens:
        op.add_column(table, sa.Column("tokens_per_minute", sa.BigInteger(), nullable=True))
        op.create_check_constraint(
            f"ck_{table}_tokens_per_minute_positive",
            table,
            "tokens_per_minute IS NULL OR tokens_per_minute >= 1",
        )


def upgrade() -> None:
    op.add_column("tenants", sa.Column("tokens_per_minute", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        "ck_tenants_tokens_per_minute_positive",
        "tenants",
        "tokens_per_minute IS NULL OR tokens_per_minute >= 1",
    )
    _add_limits("api_keys", tokens=True)
    _add_limits("models", tokens=True)


def downgrade() -> None:
    for table in ("models", "api_keys"):
        op.drop_constraint(f"ck_{table}_tokens_per_minute_positive", table, type_="check")
        op.drop_column(table, "tokens_per_minute")
        op.drop_constraint(f"ck_{table}_requests_per_minute_positive", table, type_="check")
        op.drop_column(table, "requests_per_minute")
    op.drop_constraint("ck_tenants_tokens_per_minute_positive", "tenants", type_="check")
    op.drop_column("tenants", "tokens_per_minute")
