"""OIDC subject on admin users

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("admin_users", sa.Column("oidc_subject", sa.String(length=255), nullable=True))
    op.create_index(
        "uq_admin_users_oidc_subject",
        "admin_users",
        ["oidc_subject"],
        unique=True,
        postgresql_where=sa.text("oidc_subject IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_admin_users_oidc_subject", table_name="admin_users")
    op.drop_column("admin_users", "oidc_subject")
