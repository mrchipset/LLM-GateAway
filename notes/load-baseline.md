# Load baseline: method and results

Status: harness exists (`scripts/loadtest`). Numbers are filled in per environment; this
note records the method and the decision rules, not a single machine's numbers.

## 1. What is measured

The gateway data plane with real auth, quota, billing, usage writes, and PostgreSQL. The
upstream provider is a local stub with configurable time-to-first-byte, per-token delay, and
error rate. Gateway overhead is therefore `measured latency - configured stub latency`.

Real provider calls are used once per provider (20–50 requests) to calibrate the stub and
verify the SSE/usage shape. RPS ramps never hit a real provider: they would measure the
provider's rate limiter, cost money, and cannot be fault-injected.

## 2. What must be real

| Component | Real | Why |
|---|---|---|
| gateway process | yes | that is the subject |
| PostgreSQL | yes | auth lookup, month aggregate, usage insert are the hot path |
| seeded usage volume | yes | an empty month aggregate measures nothing |
| API keys, tenants, limits | yes | each request does several reads and writes |
| streaming | yes | SSE framing, disconnect, and TTFT only exist on this path |
| upstream provider | no (stub) | cost, rate limits, no fault injection |

## 3. Runs

Each run records: machine, worker count, `usage_records` rows in the month, stub settings,
k6 rate/duration, and the numbers below.

### Run A — baseline

No plan, no budget, no price required. Non-streaming, stub 40 ms TTFB + 15 ms/token.

Record: `http_reqs` rate, `http_req_failed`, latency p50/p95/p99, `gateway_request_duration_seconds`,
CPU/RSS, `pg_stat_activity` connection count, pool wait.

### Run B — billing on (the important comparison)

Same tenant, same rate, with `plan_tokens` + `monthly_cost_budget` + a price. Every request
now adds the month aggregate and the price lookup.

Decision rule: if p95 grows by more than ~30% at the same RPS, or the DB connection count
saturates before CPU does, G1.3 starts with a monthly counter row and price caching instead of
a broader refactor. If p95 moves less than 10%, billing is not the bottleneck and G1.3 waits.

### Run C — streaming

`--stream`, moderate rate. Watch: full-stream duration distribution, `gateway_upstream_ttft_seconds`,
client disconnects (`llm.client_disconnected`), and whether usage rows still appear for
disconnected streams.

### Run D — faults

Stub `STUB_ERROR_RATE=0.05` with `STUB_ERROR_STATUS=500`, then separately 429. Watch retry
amplification (`gateway_upstream_requests_total` vs `gateway_requests_total`), error budget,
and whether metrics distinguish upstream failure from gateway failure.

## 4. Results template

| Run | RPS target | Achieved | err % | p50 | p95 | p99 | DB conns | CPU | Notes |
|---|---|---|---|---|---|---|---|---|---|
| A baseline | | | | | | | | | |
| B billing | | | | | | | | | |
| C stream | | | | | | | | | |
| D faults | | | | | | | | | |

## 5. Interpretation notes

- Quotas and budgets are soft against concurrency: rejected requests are those that started
  after the limit was crossed, so a run at the limit shows a small number of accepted
  requests above it. That is expected, not a regression.
- `last_used_at` is written on every authenticated request; if DB write latency dominates,
  that is the first thing to sample or batch.
- The month aggregate grows with the month's traffic. A run on day 1 and a run on day 28 are
  not comparable unless `warm_usage.py` seeded the same row count.
- The stub is Python asyncio. Monitor its CPU; if it approaches the gateway's, the harness is
  the bottleneck, not the gateway.

## 6. Commands

See `scripts/loadtest/README.md`. Short version:

```powershell
$env:GATEWAY_DATABASE_URL = "postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway"
uv run python scripts/loadtest/run_loadtest.py --storage postgres --rate 50 --duration 120s
uv run python scripts/loadtest/warm_usage.py --rows 200000
```

## 7. Results — 2026-11-04 (Linux host)

Environment: 8 vCPU, 31 GiB, Ubuntu; k6 v2.3.0 (snap); gateway as a **single uvicorn
worker** with a 50-entry connection pool; PostgreSQL 16.2 embedded through `pgserver` over a
Unix socket; everything co-located (the generator competes with the gateway). Upstream is the
local stub; `ttfb/token/tokens` differ per run as noted.

| Run | Stub | Target RPS | Achieved | err | p50 | p95 | p99 | Notes |
|---|---|---|---|---|---|---|---|---|
| baseline, realistic upstream | 40 ms + 32×15 ms | 50 | 49.8 | 0 | 534 ms | 538 ms | 551 ms | upstream-dominated |
| baseline, fast upstream | 5 ms + 8×1 ms | 100 | 100 | 0 | 27 ms | 30 ms | 39 ms | gateway CPU ~81% |
| baseline, fast upstream (repeat) | 5 ms + 8×1 ms | 60 | 60 | 0 | 34 ms | 53 ms | 63 ms | gateway CPU ~67% |
| billing, 50k rows | fast | 100 | 78 | 0 | 5.34 s | 9.94 s | 12.06 s | gateway CPU 100%, 500 VUs |
| billing, 50k rows | fast | 60 | 60 | 0 | 69 ms | 83 ms | 89 ms | gateway CPU ~69% |
| billing, 215k rows | fast | 60 | **39.6** | 0 | 11.5 s | 15.3 s | 16.8 s | DB-bound, 500 VUs |
| streaming | 20 ms + 32×5 ms | 30 | 30 | 0 | 213 ms | 245 ms | 258 ms | TTFT avg 22.4 ms (stub 20 ms) |
| faults, 5% 500 | fast | 50 | 49.9 | **0.01%** | 37 ms | 73 ms | 441 ms | 317/6318 upstream 500 |

### Findings

1. **The month aggregate is the collapse.** 50k rows at 100 RPS drove p95 to 9.94 s; 215k rows
   at 60 RPS could only sustain 39.6 RPS and p95 15.3 s. The gateway CPU stayed at 63–100% of
   one core, so this is not only DB CPU: each request scans the tenant's month of rows.
2. **A single worker saturates around 100 RPS** for this workload. Baseline at 100 RPS already
   used ~81% of one core; 8 cores were idle. Worker configuration is a separate capacity lever
   (G1.5), but shared rate limiting/health must land first (G1.2).
3. **Billing cost at a sustainable rate:** at 60 RPS with 50k rows, p95 moved 53 → 83 ms
   (+57%, +30 ms). The damage is the O(rows) query, not the price lookup.
4. **Faults behave:** 5% injected 500s produced 317 failed upstream attempts out of 6318, one
   client-visible failure (0.01%), and retry amplification 1.053. p99 441 ms reflects retries.
5. **Streaming overhead is small:** client TTFT averaged 22.4 ms against a 20 ms stub delay, so
   the gateway adds ~2.4 ms before the first token at 30 RPS.

### Decisions

- **G1.3 order changes:** (1) monthly usage counter/cached totals so billing authorization is
  O(1), (2) price cache, (3) key/tenant cache, (4) batched usage writes. Do not tune PostgreSQL
  or add workers first: the query shape is the cause, and 8 cores were idle.
- Re-run this same matrix after the monthly counter lands; success means 215k rows at 60 RPS
  returns to the baseline p95 (within ~10%).
- Do not enable multiple workers while rate limits and cooldown are process-local.

### Environment caveats

- The SSH account is not in the `docker` group (`/var/run/docker.sock` is root-only), so the
  Docker Compose stack could not be used. The test ran from the repository with `uv` against an
  embedded PostgreSQL 16.2 (`pgserver`) over a Unix socket. Query planning is comparable, but
  shared_buffers and server settings are defaults, not the production Compose values.
- k6 is a snap. Snap confinement cannot read `/data`; the script was copied to `$HOME` and the
  runner was given `--k6-script`.
- Co-located generator: numbers are a lower bound for throughput; cross-host k6 will be run
  after the G1.3 change to confirm.

