"""trace context on usage and audit records

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usage_records",
        sa.Column("trace_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_usage_records_trace_id",
        "usage_records",
        ["trace_id"],
        unique=False,
    )

    op.add_column(
        "audit_requests",
        sa.Column("trace_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_audit_requests_trace_id",
        "audit_requests",
        ["trace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_requests_trace_id", table_name="audit_requests")
    op.drop_column("audit_requests", "trace_id")

    op.drop_index("ix_usage_records_trace_id", table_name="usage_records")
    op.drop_column("usage_records", "trace_id")
