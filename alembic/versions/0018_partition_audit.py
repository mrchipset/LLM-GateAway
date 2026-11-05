"""partition audit requests and turn diffs by month

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-05

PostgreSQL requires the partition key in every primary key. The audit tables are
therefore rebuilt with ``(request_id, created_at)`` primary keys, and the diff table
carries a composite foreign key so ``ON DELETE CASCADE`` keeps working across
partitions. A DEFAULT partition catches rows for months that have no partition yet;
``scripts/audit_partitions.py`` creates upcoming months ahead of time.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUEST_COLUMNS = (
    "request_id, session_id, parent_request_id, tenant_id, api_key_id, turn_index, "
    "match_method, change_type, model_id, provider, is_stream, request_messages, "
    "message_hashes, request_params, response_content, response_tool_calls, "
    "response_content_hash, finish_reason, status, prompt_tokens, completion_tokens, "
    "cached_tokens, total_tokens, truncated, trace_id, created_at"
)
_DIFF_COLUMNS = (
    "request_id, previous_request_id, change_type, common_prefix, added_messages, "
    "modified_messages, removed_messages, parameter_changes, usage_delta, "
    "response_change, created_at"
)

_CREATE_REQUESTS = """
CREATE TABLE audit_requests (
    request_id varchar(64) NOT NULL,
    session_id uuid NOT NULL,
    parent_request_id varchar(64),
    tenant_id uuid NOT NULL,
    api_key_id uuid NOT NULL,
    turn_index integer NOT NULL,
    match_method varchar(16) NOT NULL,
    change_type varchar(24) NOT NULL,
    model_id varchar(200) NOT NULL,
    provider varchar(32) NOT NULL,
    is_stream boolean NOT NULL,
    request_messages jsonb NOT NULL,
    message_hashes jsonb NOT NULL,
    request_params jsonb NOT NULL,
    response_content text,
    response_tool_calls jsonb,
    response_content_hash varchar(64),
    finish_reason varchar(64),
    status varchar(24) NOT NULL,
    prompt_tokens integer,
    completion_tokens integer,
    cached_tokens integer,
    total_tokens integer,
    truncated boolean NOT NULL DEFAULT false,
    trace_id varchar(32),
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_audit_requests_partitioned PRIMARY KEY (request_id, created_at),
    CONSTRAINT fk_audit_requests_session_id FOREIGN KEY (session_id)
        REFERENCES audit_sessions (id) ON DELETE CASCADE,
    CONSTRAINT fk_audit_requests_tenant_id FOREIGN KEY (tenant_id)
        REFERENCES tenants (id) ON DELETE RESTRICT,
    CONSTRAINT fk_audit_requests_api_key_id FOREIGN KEY (api_key_id)
        REFERENCES api_keys (id) ON DELETE RESTRICT
) PARTITION BY RANGE (created_at)
"""

_CREATE_DIFFS = """
CREATE TABLE audit_turn_diffs (
    request_id varchar(64) NOT NULL,
    previous_request_id varchar(64),
    change_type varchar(24) NOT NULL,
    common_prefix integer NOT NULL,
    added_messages jsonb NOT NULL,
    modified_messages jsonb NOT NULL,
    removed_messages jsonb NOT NULL,
    parameter_changes jsonb NOT NULL,
    usage_delta jsonb NOT NULL,
    response_change jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT pk_audit_turn_diffs_partitioned PRIMARY KEY (request_id, created_at),
    CONSTRAINT fk_audit_turn_diffs_request_id FOREIGN KEY (request_id, created_at)
        REFERENCES audit_requests (request_id, created_at) ON DELETE CASCADE
) PARTITION BY RANGE (created_at)
"""

_CREATE_REQUESTS_ROLLBACK = """
CREATE TABLE audit_requests_rollback (
    request_id varchar(64) NOT NULL,
    session_id uuid NOT NULL,
    parent_request_id varchar(64),
    tenant_id uuid NOT NULL,
    api_key_id uuid NOT NULL,
    turn_index integer NOT NULL,
    match_method varchar(16) NOT NULL,
    change_type varchar(24) NOT NULL,
    model_id varchar(200) NOT NULL,
    provider varchar(32) NOT NULL,
    is_stream boolean NOT NULL,
    request_messages jsonb NOT NULL,
    message_hashes jsonb NOT NULL,
    request_params jsonb NOT NULL,
    response_content text,
    response_tool_calls jsonb,
    response_content_hash varchar(64),
    finish_reason varchar(64),
    status varchar(24) NOT NULL,
    prompt_tokens integer,
    completion_tokens integer,
    cached_tokens integer,
    total_tokens integer,
    truncated boolean NOT NULL DEFAULT false,
    trace_id varchar(32),
    created_at timestamp with time zone NOT NULL
)
"""

_CREATE_DIFFS_ROLLBACK = """
CREATE TABLE audit_turn_diffs_rollback (
    request_id varchar(64) NOT NULL,
    previous_request_id varchar(64),
    change_type varchar(24) NOT NULL,
    common_prefix integer NOT NULL,
    added_messages jsonb NOT NULL,
    modified_messages jsonb NOT NULL,
    removed_messages jsonb NOT NULL,
    parameter_changes jsonb NOT NULL,
    usage_delta jsonb NOT NULL,
    response_change jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL
)
"""


def _month_start(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def _months_between(start: datetime, end: datetime) -> Iterable[datetime]:
    current = _month_start(start)
    last = _month_start(end)
    while current <= last:
        yield current
        current = _next_month(current)


def _create_partition(table: str, month: datetime) -> None:
    name = f"{table}_{month:%Y_%m}"
    end = _next_month(month)
    op.execute(
        f'CREATE TABLE IF NOT EXISTS "{name}" PARTITION OF {table} '
        f"FOR VALUES FROM ('{month.isoformat()}') TO ('{end.isoformat()}')"
    )


def _existing_months(table: str) -> list[datetime]:
    bind = op.get_bind()
    row = bind.execute(sa.text(f"SELECT min(created_at), max(created_at) FROM {table}")).one()
    if row[0] is None or row[1] is None:
        return []
    return list(_months_between(row[0], row[1]))


def upgrade() -> None:
    op.execute("ALTER TABLE audit_turn_diffs RENAME TO audit_turn_diffs_legacy")
    op.execute("ALTER TABLE audit_requests RENAME TO audit_requests_legacy")

    for index in (
        "ix_audit_requests_session_turn",
        "ix_audit_requests_tenant_created",
        "ix_audit_requests_parent_request_id",
        "ix_audit_requests_api_key_created",
        "ix_audit_requests_trace_id",
    ):
        op.execute(f"DROP INDEX IF EXISTS {index}")
    for constraint, table in (
        ("fk_audit_turn_diffs_request_id", "audit_turn_diffs_legacy"),
        ("fk_audit_requests_session_id", "audit_requests_legacy"),
        ("fk_audit_requests_tenant_id", "audit_requests_legacy"),
        ("fk_audit_requests_api_key_id", "audit_requests_legacy"),
    ):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")

    months = sorted(
        set(_existing_months("audit_requests_legacy"))
        | set(_existing_months("audit_turn_diffs_legacy"))
    )
    now = datetime.now(UTC)
    months = sorted(set(months) | {_month_start(now), _next_month(_month_start(now))})

    op.execute(_CREATE_REQUESTS)
    op.execute(_CREATE_DIFFS)
    for month in months:
        _create_partition("audit_requests", month)
        _create_partition("audit_turn_diffs", month)
    op.execute(
        "CREATE TABLE IF NOT EXISTS audit_requests_default PARTITION OF audit_requests DEFAULT"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS audit_turn_diffs_default PARTITION OF audit_turn_diffs DEFAULT"
    )

    for name, columns in (
        ("ix_audit_requests_session_turn", "session_id, turn_index"),
        ("ix_audit_requests_tenant_created", "tenant_id, created_at"),
        ("ix_audit_requests_parent_request_id", "parent_request_id"),
        ("ix_audit_requests_api_key_created", "api_key_id, created_at"),
        ("ix_audit_requests_trace_id", "trace_id"),
    ):
        op.execute(f"CREATE INDEX {name} ON audit_requests ({columns})")

    op.execute(
        f"INSERT INTO audit_requests ({_REQUEST_COLUMNS}) "
        f"SELECT {_REQUEST_COLUMNS} FROM audit_requests_legacy"
    )
    op.execute(
        f"INSERT INTO audit_turn_diffs ({_DIFF_COLUMNS}) "
        f"SELECT {_DIFF_COLUMNS} FROM audit_turn_diffs_legacy"
    )

    op.execute("DROP TABLE audit_turn_diffs_legacy")
    op.execute("DROP TABLE audit_requests_legacy")


def downgrade() -> None:
    op.execute(_CREATE_REQUESTS_ROLLBACK)
    op.execute(_CREATE_DIFFS_ROLLBACK)
    op.execute(
        f"INSERT INTO audit_requests_rollback ({_REQUEST_COLUMNS}) "
        f"SELECT {_REQUEST_COLUMNS} FROM audit_requests"
    )
    op.execute(
        f"INSERT INTO audit_turn_diffs_rollback ({_DIFF_COLUMNS}) "
        f"SELECT {_DIFF_COLUMNS} FROM audit_turn_diffs"
    )

    op.execute("DROP TABLE audit_turn_diffs")
    op.execute("DROP TABLE audit_requests")
    op.execute("ALTER TABLE audit_requests_rollback RENAME TO audit_requests")
    op.execute("ALTER TABLE audit_turn_diffs_rollback RENAME TO audit_turn_diffs")

    op.execute(
        "ALTER TABLE audit_requests ADD CONSTRAINT audit_requests_pkey PRIMARY KEY (request_id)"
    )
    op.execute(
        "ALTER TABLE audit_turn_diffs ADD CONSTRAINT audit_turn_diffs_pkey PRIMARY KEY (request_id)"
    )
    op.execute(
        "ALTER TABLE audit_turn_diffs ADD CONSTRAINT fk_audit_turn_diffs_request_id "
        "FOREIGN KEY (request_id) REFERENCES audit_requests (request_id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE audit_requests ADD CONSTRAINT fk_audit_requests_session_id "
        "FOREIGN KEY (session_id) REFERENCES audit_sessions (id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE audit_requests ADD CONSTRAINT fk_audit_requests_tenant_id "
        "FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE audit_requests ADD CONSTRAINT fk_audit_requests_api_key_id "
        "FOREIGN KEY (api_key_id) REFERENCES api_keys (id) ON DELETE RESTRICT"
    )
    for name, columns in (
        ("ix_audit_requests_session_turn", "session_id, turn_index"),
        ("ix_audit_requests_tenant_created", "tenant_id, created_at"),
        ("ix_audit_requests_parent_request_id", "parent_request_id"),
        ("ix_audit_requests_api_key_created", "api_key_id, created_at"),
        ("ix_audit_requests_trace_id", "trace_id"),
    ):
        op.execute(f"CREATE INDEX {name} ON audit_requests ({columns})")
