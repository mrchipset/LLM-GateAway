# Load test kit

Reproducible capacity measurements for the data plane. The gateway is real, PostgreSQL is
real, auth/quota/billing/usage are real; only the **upstream provider** is a local stub, so
a run is deterministic and costs nothing.

## Why a stub upstream

- real provider calls are rate limited, paywalled, and noisy; you would measure them, not us
- latency and failures must be controllable (`STUB_TTFB_MS`, `STUB_TOKEN_MS`, `STUB_ERROR_RATE`)
- gateway overhead = measured latency − configured stub latency

Real calls still matter once per provider: 20–50 requests to calibrate the stub's TTFT and
verify the usage/SSE shape. Do not run a ramp against a real provider.

## Prerequisites

- `k6` on PATH (`winget install k6` / `brew install k6` / the official binary)
- PostgreSQL for a meaningful baseline; memory storage only proves the wiring works
- migrations applied: `uv run alembic upgrade head`

## Quick functional run (memory, numbers not representative)

```powershell
uv run python scripts/loadtest/run_loadtest.py --rate 5 --duration 20s --skip-k6
```

It starts the stub and the gateway, bootstraps a `loadtest-admin` owner, seeds a tenant,
model and key, sends one smoke request, and prints the gateway URL, metrics URL, and the k6
command it would have run.

## Baseline run (PostgreSQL)

```powershell
$env:GATEWAY_DATABASE_URL = "postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway"
uv run python scripts/loadtest/run_loadtest.py --storage postgres --rate 50 --duration 120s
```

Seed a month of usage first, otherwise the per-request month aggregate measures an empty
table:

```powershell
uv run python scripts/loadtest/warm_usage.py --rows 200000
```

`warm_usage.py` needs a tenant and key from a previous `run_loadtest.py`/`seed.py` run.

## The four runs that matter

| Run | Command shape | Question |
|---|---|---|
| baseline | `--rate 50 --duration 120s` | what is the gateway's own ceiling? |
| billing on | add `PLAN_TOKENS`, `MONTHLY_COST_BUDGET`, `PRICE_*` via `seed.py` env | how much does the two-query billing path cost? |
| streaming | `--stream --rate 20 --duration 120s` | connection handling, stream tail latency |
| faults | stub `--error-rate 0.05` | retry amplification, error budget, metrics signal |

For the billing comparison, seed once without billing and once with:

```powershell
$env:PLAN_TOKENS = "100000000"
$env:MONTHLY_COST_BUDGET = "1000"
$env:PRICE_INPUT_PER_MILLION = "0.28"
$env:PRICE_OUTPUT_PER_MILLION = "0.42"
uv run python scripts/loadtest/seed.py
```

## What to collect

From k6: `http_reqs` rate, `http_req_failed`, `gateway_chat_latency` p50/p95/p99.

From the gateway `/metrics` (printed by the runner):

- `gateway_request_duration_seconds` p95/p99
- `gateway_upstream_ttft_seconds` p50/p95
- `gateway_upstream_requests_total{status}` — retries and injected failures
- `gateway_rejections_total{reason}` — quota/rate/budget rejections
- process CPU/RSS and PostgreSQL `pg_stat_activity` during the run

Record the machine, worker count, DB size, and stub settings with every result; a number
without those is not comparable.

## Running the generator on another machine

The runner binds to loopback by default. To drive the gateway from a second host, bind it
to the LAN interface and keep metrics local:

```powershell
uv run python scripts/loadtest/run_loadtest.py --host 0.0.0.0 --rate 50 --duration 120s
```

- `--host` is the gateway bind address; `--metrics-host` (default `127.0.0.1`) is separate on
  purpose: do not expose the scrape port to the LAN.
- The runner scrapes `/metrics` itself right after k6 finishes and prints the route, upstream,
  TTFT, and rejection series. If k6 runs elsewhere, pass `--skip-k6` and run it on that host
  with `-e GATEWAY_URL=http://<gateway-ip>:<port>` using the key the runner printed.
- Open only the gateway port in the firewall. On Ubuntu: `sudo ufw allow 4000/tcp`. On
  Windows: `New-NetFirewallRule -DisplayName "llm-gateway loadtest" -Direction Inbound
  -Action Allow -Protocol TCP -LocalPort 4000`.

Cross-host runs measure the network honestly; co-located runs are a lower bound because the
generator competes with the gateway.

## Caveats

- single host: the load generator competes with the gateway; use two machines for a real ceiling
- the stub is Python asyncio; above a few hundred RPS check that it is not the bottleneck
  (its CPU should stay well below the gateway's)
- k6 buffers responses, so `STREAM=true` measures full-stream duration, not TTFT
- quotas and budgets are checked before the request and settled after; concurrency overshoot
  is expected and documented in `notes/billing.md`
