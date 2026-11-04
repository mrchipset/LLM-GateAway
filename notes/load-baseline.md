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
