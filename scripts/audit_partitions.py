"""Create upcoming monthly partitions for the audit tables.

The audit tables are partitioned by ``created_at`` with a DEFAULT partition that
catches rows for months that have no explicit partition. A DEFAULT partition is a
safety net, not a plan: rows that land there must be moved before the matching
monthly partition can be created. This job creates the next months ahead of time
and reports any DEFAULT rows that block a partition instead of failing halfway.

Intended for cron or a Kubernetes CronJob, alongside ``audit_cleanup.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from llm_gateway.config import Settings

AUDIT_TABLES = ("audit_requests", "audit_turn_diffs")


@dataclass(frozen=True, slots=True)
class PartitionAction:
    table: str
    partition: str
    start: datetime
    end: datetime
    status: Literal["exists", "created", "would_create", "blocked"]
    blocking_rows: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "table": self.table,
            "partition": self.partition,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "status": self.status,
            "blocking_rows": self.blocking_rows,
        }


def _month_start(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def _months(start: datetime, count: int) -> list[datetime]:
    months = [start]
    for _ in range(count):
        months.append(_next_month(months[-1]))
    return months


def _partition_name(table: str, month: datetime) -> str:
    return f"{table}_{month:%Y_%m}"


async def _partition_exists(engine: AsyncEngine, name: str) -> bool:
    async with engine.connect() as connection:
        found = await connection.scalar(
            text(
                "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = :name AND n.nspname = current_schema()"
            ),
            {"name": name},
        )
    return found is not None


async def _default_rows(engine: AsyncEngine, table: str, start: datetime, end: datetime) -> int:
    """Rows in the DEFAULT partition that belong to the requested month."""
    default = f"{table}_default"
    if not await _partition_exists(engine, default):
        return 0
    async with engine.connect() as connection:
        count = await connection.scalar(
            text(
                f"SELECT count(*) FROM {default} "  # noqa: S608 - constant identifier
                "WHERE created_at >= :start AND created_at < :end"
            ),
            {"start": start, "end": end},
        )
    return int(count or 0)


async def _plan_and_apply(
    engine: AsyncEngine,
    *,
    months_ahead: int,
    dry_run: bool,
    now: datetime,
) -> list[PartitionAction]:
    actions: list[PartitionAction] = []
    for month in _months(_month_start(now), months_ahead):
        end = _next_month(month)
        for table in AUDIT_TABLES:
            name = _partition_name(table, month)
            if await _partition_exists(engine, name):
                actions.append(PartitionAction(table, name, month, end, "exists"))
                continue
            blocking = await _default_rows(engine, table, month, end)
            if blocking > 0:
                actions.append(PartitionAction(table, name, month, end, "blocked", blocking))
                continue
            if dry_run:
                actions.append(PartitionAction(table, name, month, end, "would_create"))
                continue
            async with engine.begin() as connection:
                # DDL statements cannot take bind parameters; the values are
                # derived from a datetime, not from user input.
                await connection.execute(
                    text(
                        f'CREATE TABLE IF NOT EXISTS "{name}" '
                        f"PARTITION OF {table} "
                        f"FOR VALUES FROM ('{month.isoformat()}') "
                        f"TO ('{end.isoformat()}')"
                    )
                )
            actions.append(PartitionAction(table, name, month, end, "created"))
    return actions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create upcoming monthly partitions for the audit tables"
    )
    parser.add_argument(
        "--months-ahead",
        type=int,
        default=3,
        choices=range(0, 37),
        metavar="N",
        help="Create the current month plus N following months (default 3, max 36)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be created without changing the schema",
    )
    return parser


async def _run(args: argparse.Namespace) -> tuple[list[PartitionAction], int]:
    settings = Settings(**{})
    if not settings.database_url:
        raise SystemExit("GATEWAY_DATABASE_URL is required")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        actions = await _plan_and_apply(
            engine,
            months_ahead=args.months_ahead,
            dry_run=args.dry_run,
            now=datetime.now(UTC),
        )
    finally:
        await engine.dispose()
    return actions, sum(1 for action in actions if action.status == "blocked")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    actions, blocked = asyncio.run(_run(args))
    print(
        json.dumps(
            {"dry_run": bool(args.dry_run), "actions": [item.to_dict() for item in actions]},
            indent=2,
            sort_keys=True,
        )
    )
    if blocked:
        print(
            "blocked partitions contain rows in the DEFAULT partition; "
            "move those rows into a monthly partition before creating it",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
