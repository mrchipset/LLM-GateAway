# Hot path: monthly usage rollup and write sampling

## Problem

The load baseline (`notes/load-baseline.md`) showed one query dominating the data plane:

- 50k usage rows and 100 RPS: p95 9.94 s, 78 RPS achieved;
- 50k rows at 60 RPS: p95 83 ms against a 53 ms baseline (+57%);
- 215k rows at 60 RPS: 39.6 RPS achieved, p95 15.3 s.

Every billed request summed the tenant's whole month before calling the upstream. The cost grew with
the month's row count, so latency degraded every day the tenant used the gateway. Two smaller
amplifiers existed as well: `last_used_at` was written on every authenticated request, and the
price lookup plus key/tenant lookups were repeated per request.

## Decisions

### One rollup row per tenant-month, updated in the same transaction

`tenant_month_usage` is keyed by `(tenant_id, period_start)` and stores prompt/completion/cached/
total/covered/billable tokens, list and billed cost, request count, and `updated_at`.
`UsageRepository.record` inserts the detail row and upserts the rollup in **one transaction**, so
the two cannot diverge through partial writes. Billing authorization (`monthly_totals`) and the
monthly quota check (`token_total`) read the single row instead of scanning detail.

The migration backfills the rollup from `usage_records` (`date_trunc('month', created_at)`), so an
upgrade starts with a correct snapshot for existing tenants.

Money stays `NUMERIC(18,6)`; increments are exact decimal additions, not floats.

Rejected: materialized views and scheduled aggregation. Both make the hot path read stale data and
add an operational job; the same-transaction upsert has neither problem.

### Month-aligned windows use the rollup, others fall back to detail

`monthly_totals`/`token_total` keep their existing signatures. If the window is exactly one UTC
calendar month (the only shape billing and quotas use), the rollup is read; any other window still
runs the detail `SUM`. This keeps ad-hoc reporting exact without giving up O(1) enforcement.

### `last_used_at` is sampled

The timestamp is informational; writing it on every request is a row update per call. A
process-local sampler (`GATEWAY_LAST_USED_SAMPLE_SECONDS`, default 60, `0` = every request) limits
the write to once per key per interval. With several workers the effective interval divides by the
worker count, which is acceptable for a display field.

### Price and key/tenant caches were not added

The measurement says the month aggregate was the bottleneck, not the single-row price lookup. Price
caching would introduce a staleness window where a newly created price is not billed (costs are
supposed to be exact from `effective_from`), and key/tenant caches would delay revocations and
limit changes. Neither risk buys measurable latency after the rollup lands. Revisit only if a new
baseline shows these lookups on the critical path.

### Batched usage writes are deferred

After the rollup, a request performs one detail INSERT plus one rollup UPSERT. Batching would
remove one round trip at the cost of losing usage on crash and complicating the transaction that
keeps the rollup and detail consistent. The re-measured baseline decides; it is not speculative
work.

## Verification

- Parity: a PostgreSQL test records priced and unpriced usage, then asserts the rollup row and the
  detail `SUM` agree on every field, and that a non-month window still uses detail.
- The load matrix is re-run against the same 215k-row tenant; success is 60 RPS back at the
  baseline p95 (about 53 ms) and throughput no longer falling with row count.

## Consequences and gaps

- The rollup is only as correct as the transaction that writes it; a manual `usage_records` edit
  would drift. A rebuild command is not implemented yet (a one-off SQL from detail to rollup is
  straightforward and documented in the migration).
- Deletes/backfills of usage rows must update the rollup; nothing in the admin API deletes usage
  today, so this is a constraint for future work.
- Per-key/model rollups are not needed by enforcement today; the usage report still scans detail.
