# Tenant quotas and rate limits

Status: implemented in `storage/rate_limits.py`, `services/limits.py`,
`api/admin/tenants.py`, and migration `0004`.

## Problem and constraints

Operators need a way to stop one tenant from exhausting shared capacity, using
only the infrastructure the project already runs. The MVP has PostgreSQL, an
in-memory mode for tests, and no Redis client. Enforcement sits on the inference
hot path and must be predictable under concurrent requests and multiple workers.

## Assumptions

- Limits are tenant-level: one monthly token quota and one requests-per-minute
  limit. Per-key limits, per-model limits, and burst shaping are out of scope.
- The quota period is the UTC calendar month `[month_start, next_month_start)`.
  Quota consumption is the sum of provider-reported `total_tokens` (cached
  tokens are already part of prompt tokens, so they are not added again).
- Quota is a **soft ceiling**: it is checked before the request, so concurrent
  or in-flight requests can overshoot it by their own usage. A hard reservation
  system would need per-request reservations and refunds.
- `null` means unlimited. Values must be >= 1; `0` is rejected instead of
  silently blocking a tenant.
- Rate limiting applies to `POST /v1/chat/completions` only. Listing models,
  health checks, and the management API are not tenant-rate-limited.
- The memory backend's limiter is process-local and for development/tests only;
  PostgreSQL is the only multi-worker-correct backend.

## Options considered

**Redis counters vs PostgreSQL.** Redis is the usual answer for shared rate
limits, but the project deliberately has no Redis client and no operational
dependency yet. A single-row PostgreSQL upsert is atomic, survives restarts, and
reuses the existing pool. The cost is one write per chat request; that is
acceptable for the MVP and is recorded as a scaling follow-up.

**Fixed window vs token bucket.** A token bucket gives smoother bursts but needs
an extra state model and more explanation for operators. A fixed 60-second
window is simple, matches the UI wording, and is enough to stop runaway usage.
The trade-off is a burst at window boundaries.

**Hard quota reservations vs a pre-request sum.** Reservations prevent
overshoot but require reserving an unknown completion size, refunds on failure,
and a durable ledger. The MVP sums current-month usage before the request and
accepts the documented overshoot.

**Enforcing in the provider adapter vs at the edge.** Enforcement lives in an
inference dependency, before any provider work, so rejected requests cost
nothing upstream and every model/provider is covered uniformly.

## Chosen approach

- `tenants.monthly_token_quota` and `tenants.requests_per_minute` are nullable
  columns with `CHECK (... IS NULL OR >= 1)`; `PATCH /api/v1/tenants/{id}`
  updates only the fields present in the body (explicit `null` clears).
- `tenant_rate_limits(tenant_id PK, window_start, count)` keeps exactly one row
  per tenant. The limiter runs one atomic
  `INSERT ... ON CONFLICT (tenant_id) DO UPDATE ... RETURNING` statement, so
  concurrent workers cannot lose increments.
- The window is a 60-second bucket derived from the injected clock. The window
  start is monotonic: a request carrying an older timestamp still consumes the
  current window's budget but can never move the window backwards or reset the
  count. `Retry-After` is the ceiling of the remaining window time, clamped to
  1..60 seconds.
- `enforce_inference_limits` depends on `require_api_key`, loads the tenant,
  checks the monthly quota first, then consumes rate-limit budget. A tenant over
  quota therefore receives `tenant_quota_exceeded` instead of burning its
  per-minute budget. Rejected requests do not create usage records.
- Errors are 429 with the OpenAI envelope: `rate_limited` (type
  `rate_limit_error`, `Retry-After` header) and `tenant_quota_exceeded` (type
  `insufficient_quota`). Logs include tenant id, limit, used tokens, and retry
  delay only.

## Trade-offs and risks

- One extra upsert per chat request, plus one `SUM(total_tokens)` per request
  when a quota is configured. Both are acceptable at MVP scale; a rollup table
  or Redis is the next step.
- Quota overshoot: requests already in flight, concurrent requests, and usage
  write failures make the ledger drift below the true upstream consumption.
- Counter drift: the limiter counts requests, not successes. A rejected request
  still consumes budget, which prevents retry storms.
- Clock skew between workers is handled monotonically, but a worker whose clock
  is far ahead can advance the window early for everyone.
- No burst allowance, no per-key limits, no per-model limits, and no UI for
  editing limits yet.
- Limits cannot be set to 0; suspending a tenant requires revoking its keys.

## References

- `src/llm_gateway/storage/rate_limits.py`
- `src/llm_gateway/services/limits.py`
- `src/llm_gateway/api/admin/tenants.py`
- `alembic/versions/0004_tenant_limits_and_rate_limits.py`
- `notes/tenants.md`, `notes/usage-accounting.md`
