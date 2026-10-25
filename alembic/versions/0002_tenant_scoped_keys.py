"""tenant scoped api keys

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25

"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_DEFAULT_TENANT_NAME = "default"


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenants_name", "tenants", ["name"], unique=True)

    op.execute(
        sa.text("INSERT INTO tenants (id, name, created_at) VALUES (:id, :name, now())").bindparams(
            id=UUID(_DEFAULT_TENANT_ID), name=_DEFAULT_TENANT_NAME
        )
    )

    op.add_column("api_keys", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text("UPDATE api_keys SET tenant_id = :id WHERE tenant_id IS NULL").bindparams(
            id=UUID(_DEFAULT_TENANT_ID)
        )
    )
    op.alter_column("api_keys", "tenant_id", nullable=False)

    op.create_foreign_key(
        "fk_api_keys_tenant_id",
        "api_keys",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_tenant_id", table_name="api_keys")
    op.drop_constraint("fk_api_keys_tenant_id", "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "tenant_id")
    op.drop_index("ix_tenants_name", table_name="tenants")
    op.drop_table("tenants")
