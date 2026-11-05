# Shared rate limiting: Redis token bucket

## Problem

Tenant request limits lived in one PostgreSQL row (`tenant_rate_limits`) updated by every request:

- each inference request paid a database write for the counter, on the same hot path the load
  baseline already showed collapsing;
- a fixed 60-second window lets a client spend a full budget at the end of one window and another
  at the start of the next, so the real burst is 2x the configured limit;
- with more than one gateway process, each process keeps its own window, multiplying the limit by
  the worker count.

## Options considered

**Sliding-window log (Redis sorted set).** Exact, but stores one member per request and needs a
`ZREMRANGEBYSCORE` + `ZCARD` per call. Memory grows with traffic, and the per-request cost is
proportional to the log operations.

**Fixed window in Redis.** Cheap, but keeps the 2x boundary burst and makes the boundary an
attack surface.

**Token bucket.** One hash per tenant (`tokens`, `ts`), constant memory, one script call, and the
burst is capped by the bucket capacity. Refill is continuous, so a client that was throttled gets
capacity back steadily instead of all at once.

Chosen: token bucket. `limit` is both the capacity and the per-minute refill rate, so one number
keeps its existing meaning.

## Decisions

### One Lua script owns the state transition

`HMGET` → refill by elapsed time → take or compute wait → `HSET` + `PEXPIRE` runs inside a single
`EVAL`. If the read and write were separate round trips, two replicas could both read the last
token and both be admitted.

The script returns `{allowed, remaining, wait_ms}`; the client only converts types.

### The client clock drives refill, with a monotonic clamp

Refill uses `now` from the injected `Clock`, not `TIME` inside Redis, because the application
already has one time source for quotas and billing and tests can control it. The risk is skew
between replicas; the script clamps a backwards clock to the stored timestamp (`if now_ms < t then
now_ms = t`), so skew can only under-refill, never create tokens.

Rejected: Redis `TIME`. It removes the skew question but makes the behavior untestable without
waiting, and introduces a second clock into quota decisions.

### Failure is a policy, not an accident

`GATEWAY_RATE_LIMIT_FAIL_OPEN` (default `true`) decides what happens when Redis times out or
errors:

- fail-open: admit the request, log `rate_limit_unavailable`, increment
  `gateway_rate_limit_degraded{reason}`. Chosen as the default because a limiter outage taking
  down all inference is a bigger blast radius than a temporary limit bypass, and the metric makes
  it visible.
- fail-closed: return 503 `rate_limiter_unavailable` with `Retry-After: 1`. In this mode the
  container also registers a `rate_limiter` readiness check, because rejecting every request while
  advertising readiness would make the orchestrator keep routing traffic to a broken instance.

The Redis call is bounded by `GATEWAY_RATE_LIMIT_REDIS_TIMEOUT_SECONDS` (default 0.2 s), so a hung
connection cannot consume the request timeout.

### Scope is staged

Tenant-level buckets shipped first. This stage adds:

- per-key buckets (`api_keys.requests_per_minute`), enforced after the tenant bucket;
- per-model buckets (`models.requests_per_minute`), enforced in the route once the payload names
  the model, so one hot model cannot exhaust the whole upstream account;
- TPM for tenant, key, and model (`tokens_per_minute`), settled from reported usage.

TPM is deliberately post-paid. Token counts arrive with the response, and reserving an estimate
before the call would repeat the pre-call reservation that billing rejected. The bucket therefore
starts at `limit`, a request is admitted while tokens remain, and the reported usage is charged
afterwards. The overshoot is bounded by one request's usage; the next request sees a negative
bucket and is rejected with 429 `token_rate_limited` until refill covers it.

Still missing:

1. in-flight concurrency (needs a lease with expiry so a crashed process cannot leak a slot);
2. shared deployment health (cooldown), which is still process-local.

Per-key/model buckets use the same `(scope, key)` namespace; the `storage` backend keeps them in
a process-local bucket, while Redis shares them across replicas.

## Consequences

- With `redis` configured, inference no longer writes a rate-limit row to PostgreSQL.
- Replicas share one budget; the 2x boundary burst is gone.
- One Redis round trip per limited request, bounded at 0.2 s, instead of one DB write.
- The bucket TTL is `capacity/refill + 1 s` (one minute plus a second), so idle tenants do not
  accumulate keys.
- Changing `requests_per_minute` keeps the bucket contents and changes capacity/refill on the next
  call; a lower limit clamps on the next refill, so a tenant can briefly exceed a newly lowered
  limit by at most the old capacity. Acceptable for an operational limit; documented here.
