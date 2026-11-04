# Audit data lifecycle: retention, deletion, export, redaction

## Problem

`audit_requests` stores request and response content for compliance investigation. Capture is
opt-in and bounded, but nothing removes data after it has served its purpose, nothing exports it
for a legal request, and nothing can prove a deletion. That makes the table a growing liability
rather than an asset.

Constraints:

- Content is PII by default. Every new read path is another place it can leak.
- Deletion must be provable: a count before, a count after, and no hidden copies.
- The write path is already best-effort and must not get slower or fail more.
- PostgreSQL + Alembic, additive migrations only.
- The scheduler in the target environment is a cron-like job, not an in-process worker.

## Decisions

### Retention is inherited, not duplicated

`tenants.audit_retention_days` is nullable: `NULL` inherits the global
`GATEWAY_AUDIT_RETENTION_DAYS` (default 90), `0` is a legal hold that never deletes, and a
positive value overrides the default. The migration allows `>= 0` for exactly that reason.

Rejected: a separate retention table. One integer per tenant does not justify a join on the
request path or an extra migration surface.

### Cleanup is a CLI job, not an HTTP endpoint

`scripts/audit_cleanup.py` runs one pass and exits: resolve per-tenant cutoffs, delete requests
in bounded batches, then delete sessions that no longer have requests. A long-running mutation
behind the admin API would need job tracking, cancellation, and a second authorization model for
little gain; a CLI works in cron, systemd timers, and a Kubernetes Job unchanged.

Batching matters: a single `DELETE` over a month of traffic holds locks and grows the WAL. The
job deletes at most `--batch-size` rows per statement (default 5000), commits between batches, and
stops after `--max-batches` so a misconfiguration cannot delete a year of data in one run.

Order is fixed by the foreign keys: diffs cascade with requests, so requests first, then
sessions with `NOT EXISTS (request)`. Deleting sessions first would violate the RESTRICT FK.

### Hard delete only

There is no soft-delete flag. A soft delete keeps the bytes, which is the thing retention is
supposed to remove, and every read path would have to remember to filter. The admin audit trail
records that a deletion happened; the content itself is gone.

### Export streams with keyset pagination

`GET /api/v1/audit/export` supports `format=jsonl|csv`, requires `tenant_id` and a
`since`/`until` window, and streams rows ordered by `(created_at, request_id)`. Keyset pagination
instead of `OFFSET` keeps a long export from re-reading the table and from drifting when new rows
arrive mid-export.

Export includes content because that is the point of an export; it is restricted to
`owner`/`auditor`, the response is `Content-Disposition: attachment` so it is not rendered, and
nothing is written to browser storage. No UI button yet: an operator uses `curl` or the CLI.

### Redaction happens at capture, before hashing

`GATEWAY_AUDIT_REDACT_PATTERNS` is a JSON array of `{"name", "pattern"}` regex rules. Matches are
replaced with `[redacted:<name>]` in messages, response content, tool calls, and parameters
before hashes and diffs are computed, so prefix matching and change detection stay consistent
between two redacted turns. Only the rule name and the hit count are recorded; matched text never
reaches a log, metric label, or the database.

Rejected: redacting at export/read time. The plaintext would still sit on disk, which is what the
compliance requirement is about.

### Partitioning is deferred with a trigger

`audit_requests` has `(tenant_id, created_at)` and the cleanup job deletes per tenant, so the
existing index covers the scan. Monthly `PARTITION BY RANGE (created_at)` is the right answer
above roughly 50M rows or when a single cleanup takes longer than its schedule window; until
then it would add migration and query complexity, including a primary-key change on
`request_id`.

## Consequences

- A tenant can be put on legal hold (`0`) without disabling audit capture.
- Deletion returns `requests_deleted` and `sessions_deleted`, and a follow-up count proves zero
  rows remain in the window. There is no object storage in this deployment, so "no residue"
  means no rows.
- Cleanup failures are logged and counted (`gateway_audit_cleanup_failures_total`); the job exits
  non-zero so the scheduler can alert.
- Redaction adds one regex pass per captured payload. With audit off (the default) it costs
  nothing; with audit on it is bounded by `audit_max_content_bytes`.

## Open gaps

- No admin UI for export or deletion; the API and CLI are the interface.
- Login success/failure events still go to logs and metrics only, not to `admin_audit_events`.
- No per-key retention: retention is per tenant because that is the unit that owns the contract.
