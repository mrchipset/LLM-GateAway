"""Run the audit retention cleanup lane once.

Intended for an external scheduler (cron, systemd timer, Kubernetes CronJob). The
job prints a JSON report without audit content and exits non-zero when any tenant
failed so the scheduler can alert.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from uuid import UUID

from llm_gateway.config import Settings
from llm_gateway.container import build_container
from llm_gateway.services.audit_retention import AuditRetentionService, CleanupReport


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Delete audit rows past their retention window")
    parser.add_argument(
        "--tenant",
        action="append",
        type=UUID,
        default=None,
        help="Tenant id to clean; repeatable. Defaults to every tenant.",
    )
    parser.add_argument("--batch-size", type=_positive_int, default=5000)
    parser.add_argument("--max-batches", type=_positive_int, default=100)
    parser.add_argument("--dry-run", action="store_true", help="Count rows without deleting them")
    return parser


async def _execute(args: argparse.Namespace) -> CleanupReport:
    settings = Settings(**{})
    container = build_container(settings)
    try:
        service = AuditRetentionService(
            settings=settings,
            audit=container.audit,
            tenants=container.tenants,
            clock=container.clock,
        )
        return await service.run(
            tenant_ids=args.tenant,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            max_batches=args.max_batches,
        )
    finally:
        await container.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = asyncio.run(_execute(args))
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
