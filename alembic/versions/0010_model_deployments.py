"""model deployments for multi-upstream routing

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_deployments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("upstream_model", sa.String(length=256), nullable=False),
        sa.Column("credential_env", sa.String(length=100), nullable=True),
        sa.Column("base_url", sa.String(length=2048), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["models.id"],
            name="fk_model_deployments_model_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "weight >= 1 AND weight <= 100",
            name="ck_model_deployments_weight",
        ),
    )
    op.create_index(
        "uq_model_deployments_model_name",
        "model_deployments",
        ["model_id", "name"],
        unique=True,
    )
    op.create_index(
        "ix_model_deployments_model",
        "model_deployments",
        ["model_id", "enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_deployments_model", table_name="model_deployments")
    op.drop_index("uq_model_deployments_model_name", table_name="model_deployments")
    op.drop_table("model_deployments")
