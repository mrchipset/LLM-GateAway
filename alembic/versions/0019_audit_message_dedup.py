"""deduplicated audit message store

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_message_blobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("original_bytes", sa.Integer(), nullable=False),
        sa.Column("stored_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_audit_message_blobs_tenant_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "content_hash",
            name="uq_audit_message_blobs_tenant_hash",
        ),
    )
    op.create_table(
        "audit_request_messages",
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("blob_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["blob_id"],
            ["audit_message_blobs.id"],
            name="fk_audit_request_messages_blob_id",
        ),
        sa.ForeignKeyConstraint(
            ["request_id", "created_at"],
            ["audit_requests.request_id", "audit_requests.created_at"],
            name="fk_audit_request_messages_request_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "request_id",
            "created_at",
            "ordinal",
            name="pk_audit_request_messages",
        ),
    )
    op.create_index(
        "ix_audit_request_messages_blob_id",
        "audit_request_messages",
        ["blob_id"],
    )
    op.alter_column(
        "audit_requests",
        "request_messages",
        existing_type=postgresql.JSONB(),
        nullable=True,
    )


def downgrade() -> None:
    # New rows have no inline snapshot; rebuild one from the deduplicated store
    # before dropping it so the legacy schema remains readable.
    op.execute(
        sa.text(
            """
            UPDATE audit_requests AS r
            SET request_messages = COALESCE(
                (
                    SELECT jsonb_agg(b.content ORDER BY m.ordinal)
                    FROM audit_request_messages AS m
                    JOIN audit_message_blobs AS b ON b.id = m.blob_id
                    WHERE m.request_id = r.request_id
                      AND m.created_at = r.created_at
                ),
                '[]'::jsonb
            )
            WHERE r.request_messages IS NULL
            """
        )
    )
    op.alter_column(
        "audit_requests",
        "request_messages",
        existing_type=postgresql.JSONB(),
        nullable=False,
    )
    op.drop_index("ix_audit_request_messages_blob_id", table_name="audit_request_messages")
    op.drop_table("audit_request_messages")
    op.drop_table("audit_message_blobs")
