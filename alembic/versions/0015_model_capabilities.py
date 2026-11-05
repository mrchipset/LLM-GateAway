"""model capability metadata

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("models", sa.Column("context_window", sa.Integer(), nullable=True))
    op.add_column("models", sa.Column("max_output_tokens", sa.Integer(), nullable=True))
    op.add_column(
        "models",
        sa.Column("supports_tools", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "models",
        sa.Column("supports_streaming", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_check_constraint(
        "ck_models_context_window_positive",
        "models",
        "context_window IS NULL OR context_window >= 1",
    )
    op.create_check_constraint(
        "ck_models_max_output_tokens_positive",
        "models",
        "max_output_tokens IS NULL OR max_output_tokens >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_models_max_output_tokens_positive", "models", type_="check")
    op.drop_constraint("ck_models_context_window_positive", "models", type_="check")
    op.drop_column("models", "supports_streaming")
    op.drop_column("models", "supports_tools")
    op.drop_column("models", "max_output_tokens")
    op.drop_column("models", "context_window")
