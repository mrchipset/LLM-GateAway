"""Move legacy inline audit snapshots into the deduplicated message store.

Safe to run while the gateway is serving traffic and idempotent across restarts:
each batch locks the rows it converts, and converted rows have no inline snapshot
left to pick up. Intended for an external scheduler or a one-off operator run.

Phase 1 keeps ``message_hashes``; this job only removes the duplicated
``request_messages`` payloads.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from uuid import UUID

from llm_gateway.config import Settings
from llm_gateway.container import build_container


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill audit message references from inline snapshots"
    )
    parser.add_argument(
        "--tenant",
        action="append",
        type=UUID,
        default=None,
        help="Tenant id to backfill; repeatable. Defaults to every tenant.",
    )
    parser.add_argument("--batch-size", type=_positive_int, default=100)
    parser.add_argument(
        "--include-truncated",
        action="store_true",
        help=(
            "Also convert rows whose stored messages were truncated per request. "
            "Their bodies differ per turn, so this rarely deduplicates and mostly "
            "adds references."
        ),
    )
    parser.add_argument(
        "--max-batches",
        type=_positive_int,
        default=None,
        help="Stop after this many batches per tenant; default is until drained.",
    )
    return parser


async def _execute(args: argparse.Namespace) -> dict[str, int]:
    settings = Settings(**{})
    container = build_container(settings)
    try:
        targets: list[UUID | None] = list(args.tenant) if args.tenant else [None]
        report: dict[str, int] = {}
        for tenant_id in targets:
            converted = 0
            batches = 0
            while args.max_batches is None or batches < args.max_batches:
                count = await container.audit.backfill_inline_messages(
                    tenant_id=tenant_id,
                    batch_size=args.batch_size,
                    include_truncated=args.include_truncated,
                )
                batches += 1
                converted += count
                if count < args.batch_size:
                    break
            report["all" if tenant_id is None else str(tenant_id)] = converted
        return report
    finally:
        await container.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = asyncio.run(_execute(args))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
