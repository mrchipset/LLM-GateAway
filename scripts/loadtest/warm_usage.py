"""Pre-seed usage rows so the per-request month aggregate is measured at scale.

The gateway sums the current month's usage before serving a billed request. An empty
table therefore measures nothing. This inserts synthetic rows for the current month,
attributed to an existing tenant and key, without touching the inference path.

Requires GATEWAY_DATABASE_URL (PostgreSQL) and a tenant created by seed.py.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

import asyncpg


def _dsn() -> str:
    dsn = os.environ.get("GATEWAY_DATABASE_URL")
    if not dsn:
        raise SystemExit("GATEWAY_DATABASE_URL is required")
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


async def _resolve(connection: asyncpg.Connection, tenant_name: str) -> tuple[str, str]:
    tenant_id = await connection.fetchval(
        "SELECT id FROM tenants WHERE name = $1",
        tenant_name,
    )
    if tenant_id is None:
        raise SystemExit(f"tenant '{tenant_name}' does not exist; run seed.py first")
    key_id = await connection.fetchval(
        "SELECT id FROM api_keys WHERE tenant_id = $1 ORDER BY created_at DESC LIMIT 1",
        tenant_id,
    )
    if key_id is None:
        raise SystemExit("no API key exists for the tenant; run seed.py first")
    return str(tenant_id), str(key_id)


async def _insert(
    connection: asyncpg.Connection,
    *,
    tenant_id: str,
    key_id: str,
    model_id: str,
    rows: int,
) -> int:
    prefix = uuid.uuid4().hex[:10]
    await connection.execute(
        """
        INSERT INTO usage_records (
            id, request_id, tenant_id, api_key_id, model_id, provider,
            prompt_tokens, completion_tokens, total_tokens, cached_tokens,
            covered_tokens, billable_tokens, list_cost, billed_cost, created_at
        )
        SELECT
            gen_random_uuid(),
            'warm-' || $5 || '-' || g,
            $1::uuid,
            $2::uuid,
            $3,
            'openai',
            800, 400, 1200, 0,
            0, 1200, 0.000120, 0.000120,
            date_trunc('month', now()) + random() * (now() - date_trunc('month', now()))
        FROM generate_series(1, $4::int) AS g
        """,
        tenant_id,
        key_id,
        model_id,
        rows,
        prefix,
    )
    total = await connection.fetchval(
        """
        SELECT count(*) FROM usage_records
        WHERE tenant_id = $1::uuid AND created_at >= date_trunc('month', now())
        """,
        tenant_id,
    )
    return int(total or 0)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--tenant-name", default=os.environ.get("TENANT_NAME", "loadtest"))
    parser.add_argument("--model-id", default=os.environ.get("MODEL_ID", "loadtest-model"))
    args = parser.parse_args()

    connection = await asyncpg.connect(_dsn())
    try:
        tenant_id, key_id = await _resolve(connection, args.tenant_name)
        total = await _insert(
            connection,
            tenant_id=tenant_id,
            key_id=key_id,
            model_id=args.model_id,
            rows=args.rows,
        )
    finally:
        await connection.close()

    print(f"usage_records in current month for {args.tenant_name}: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
