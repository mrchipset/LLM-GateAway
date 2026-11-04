# LLM-GateAway

**English** | [绠€浣撲腑鏂嘳(README.zh-CN.md)

A self-hosted, multi-provider, OpenAI-compatible LLM gateway. Current state: a runnable backend, OpenAI / DeepSeek (OpenAI-compatible) / Fake providers, tenant-scoped API keys, a model registry, PostgreSQL persistence, token usage accounting, tenant quotas and rate limiting, opt-in request/session auditing with deterministic turn diffs, and an admin console with usage, access, and audit panels.

## Current capabilities

- OpenAI-compatible `POST /v1/chat/completions` with `stream=true` and `stream=false`
- `GET /v1/models` returns the enabled models
- Provider abstraction: OpenAI and DeepSeek (OpenAI-compatible) adapters plus a deterministic Fake provider
- API key auth: only SHA-256 hashes are stored; keys support expiry, revocation, and tenant ownership
- Token usage records and aggregates: input, output, and cache-hit tokens, attributed to tenant, key, and model
- Tenant-level monthly token quotas and per-minute request limits (429 + `Retry-After`)
- Tenant-scoped model access control (default allow-all, or an explicit allowlist)
- Versioned per-model prices, per-request cost, monthly token plans with optional overage, and a monthly cost budget
- Management API: `/api/v1/keys`, `/api/v1/models`, `/api/v1/tenants`, `/api/v1/usage/{summary,by-key,series}`, `/api/v1/audit/*`, protected by the master key
- PostgreSQL persistence (SQLAlchemy 2 async + Alembic), with an in-memory mode for local development
- Structured JSON logs, request ids, optional W3C trace-context tracing (OTLP/HTTP), `/healthz`, and `/readyz`
- React + Vite + TypeScript admin console: health, models, usage, tenant management, one-time API key issuance, request audit timeline/diffs, and a per-tenant audit opt-in

Out of scope: budgets and billing, guardrails, MCP/agents, tenant-level authorization with SSO/JWT/OAuth, Redis rate limiting or caching, advanced routing and fallback, and a full dashboard.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+ (admin console only)
- Docker (optional; local PostgreSQL / Redis)

The examples use PowerShell 7. Bash users can rewrite the `Invoke-RestMethod` calls as equivalent `curl` commands.

## Quick start

### 1. Install dependencies

```powershell
uv sync
```

### 2. Prepare configuration

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace `GATEWAY_MASTER_KEY`. The placeholder value is rejected; use a sufficiently long random string:

```powershell
# Generate a local master key
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Memory mode (the default) is convenient for local experiments; API keys and models are lost on restart. The configuration below also enables the fake provider. If you only replace the master key and keep `GATEWAY_FAKE_PROVIDER_ENABLED=false` from `.env.example`, registering a fake model in step 4 returns 400 `provider_not_configured`.

```dotenv
GATEWAY_ENVIRONMENT=development
GATEWAY_MASTER_KEY=<replace with a real random value>
GATEWAY_STORAGE_BACKEND=memory
GATEWAY_FAKE_PROVIDER_ENABLED=true
```

### 3. Start the development server

Run from the repository root (`.env` is resolved relative to the working directory):

```powershell
uv run uvicorn llm_gateway.app:create_app --factory --reload --port 4000
```

Verify:

```powershell
Invoke-RestMethod http://127.0.0.1:4000/healthz
Invoke-RestMethod http://127.0.0.1:4000/readyz
```

### 4. Create an API key and register a model

The management API authenticates with the master key.

```powershell
$master = "your master key"

# Create a tenant first; every API key belongs to one tenant
$tenant = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/tenants `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"name":"local-dev"}'

# Create an inference key; the plaintext is returned exactly once
$keyResponse = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/keys `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body (@{ name = "local-dev"; tenant_id = $tenant.id } | ConvertTo-Json)

$key = $keyResponse.key
$key

# Register a fake model (requires GATEWAY_FAKE_PROVIDER_ENABLED=true)
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/models `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"id":"fake-echo","provider":"fake","upstream_model":"fake-echo"}'
```

### 5. Call the inference API

Non-streaming:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/v1/chat/completions `
  -Headers @{ Authorization = "Bearer $key" } `
  -ContentType "application/json" `
  -Body '{"model":"fake-echo","messages":[{"role":"user","content":"hello"}]}'
```

Streaming (call `curl.exe` explicitly in PowerShell to avoid the `curl` alias):

```powershell
'{"model":"fake-echo","messages":[{"role":"user","content":"hello"}],"stream":true}' |
  Set-Content body.json -Encoding utf8

curl.exe -N -X POST http://127.0.0.1:4000/v1/chat/completions `
  -H "Authorization: Bearer $key" `
  -H "Content-Type: application/json" `
  --data-binary "@body.json"

Remove-Item body.json
```

Streaming responses use SSE: each event is `data: <json>`, terminated by `data: [DONE]`.

List models:

```powershell
Invoke-RestMethod http://127.0.0.1:4000/v1/models `
  -Headers @{ Authorization = "Bearer $key" }
```

Revoke a key (`id` comes from the creation response):

```powershell
Invoke-RestMethod -Method Delete `
  -Uri "http://127.0.0.1:4000/api/v1/keys/$($keyResponse.id)" `
  -Headers @{ Authorization = "Bearer $master" }
```

## Real OpenAI

Set the following in `.env`:

```dotenv
GATEWAY_OPENAI_API_KEY=sk-...
GATEWAY_OPENAI_BASE_URL=https://api.openai.com/v1
```

Restart the service, then register a model through the management API:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/models `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"id":"gpt-4o-mini","provider":"openai","upstream_model":"gpt-4o-mini"}'
```

Clients only use the gateway's `gpt-4o-mini`; upstream model renames do not require client changes.

## DeepSeek

DeepSeek's Chat Completions API is OpenAI-compatible, so it reuses the same adapter with its own key and base URL:

```dotenv
GATEWAY_DEEPSEEK_API_KEY=sk-...
GATEWAY_DEEPSEEK_BASE_URL=https://api.deepseek.com
```

Restart the service and register a model. Model ids follow DeepSeek's current documentation; the older `deepseek-chat` / `deepseek-reasoner` ids are retired:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/models `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"id":"deepseek-flash","provider":"deepseek","upstream_model":"deepseek-flash"}'
```

Notes:

- `reasoning_content` from thinking mode is passed through to clients unchanged, including stream deltas.
- In multi-turn tool calls, historical assistant messages must include `reasoning_content`, otherwise DeepSeek returns 400.
- With `stream_options.include_usage=true`, DeepSeek attaches usage to the final content chunk and does not emit a separate usage-only chunk; the gateway forwards it as-is.
- Reasoning models can be slow to the first token; raise `GATEWAY_REQUEST_TIMEOUT_SECONDS` if needed.

## Token usage

Every successful request records one usage row (tenant, API key, model, provider) with input, output, total, and cache-hit tokens. Streaming requests are recorded too: the gateway asks the upstream for usage, but only forwards the usage chunk to the client when the client explicitly sets `stream_options.include_usage=true`.

Query the summary (master key):

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:4000/api/v1/usage/summary?tenant_id=$($tenant.id)&since=2026-10-01T00:00:00Z" `
  -Headers @{ Authorization = "Bearer $master" }
```

Optional parameters: `tenant_id`, `model_id`, `since`, `until`. Timestamps must be timezone-aware RFC 3339 strings; the window is half-open `[since, until)`. An unknown tenant returns 404.

Response example:

```json
{
  "prompt_tokens": 1200,
  "completion_tokens": 340,
  "cached_tokens": 800,
  "total_tokens": 1540,
  "requests": 12,
  "by_model": [
    {
      "model_id": "deepseek-flash",
      "provider": "deepseek",
      "prompt_tokens": 1200,
      "completion_tokens": 340,
      "cached_tokens": 800,
      "total_tokens": 1540,
      "requests": 12
    }
  ]
}
```

Semantics:

- `cached_tokens` is a subset of `prompt_tokens`, not an additional bucket. It comes from OpenAI's `prompt_tokens_details.cached_tokens` or DeepSeek's `prompt_cache_hit_tokens`; never add it to `prompt_tokens`.
- `total_tokens` is reported by the upstream and is not recomputed.
- `by_model` groups by `(model_id, provider)`; if a public model name is re-registered under another provider, it appears twice.
- A failed usage write never affects the inference response; it logs `usage_record_failed`. A client that disconnects before usage arrives may leave no record.

Per-key totals:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:4000/api/v1/usage/by-key?tenant_id=$($tenant.id)&limit=100" `
  -Headers @{ Authorization = "Bearer $master" }
```

Returns `items` ordered by total tokens desc (key name, prefix, input/output/cached/total tokens, requests). `limit` defaults to 100 and maxes at 500; keys that cannot be resolved show `null`.

Time series:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:4000/api/v1/usage/series?tenant_id=$($tenant.id)&bucket=day&since=2026-10-01T00:00:00Z" `
  -Headers @{ Authorization = "Bearer $master" }
```

- `since` / `until` default to the last 30 days; passing only `since` makes `until` the current time.
- `bucket` supports `hour` and `day`; `points` are UTC-aligned and **zero-filled** (max 1000 buckets), ready for charting.
- The console shows list and billed cost in the usage totals, per key, and beside the chart.

## Tenant quotas and rate limits

Set a tenant's monthly token quota and per-minute request limit (`null` means unlimited; values must be >= 1):

```powershell
Invoke-RestMethod -Method Patch `
  -Uri "http://127.0.0.1:4000/api/v1/tenants/$($tenant.id)" `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"monthly_token_quota":1000000,"requests_per_minute":60}'
```

- `monthly_token_quota`: cumulative upstream-reported `total_tokens` in the UTC calendar month. Once reached, `POST /v1/chat/completions` returns 429 `tenant_quota_exceeded`.
- `requests_per_minute`: fixed 60-second window. Excess requests return 429 `rate_limited` with `Retry-After` (seconds, 1鈥?0).
- PATCH only writes the fields present in the body; an explicit `null` clears that limit.
- Quotas are soft: they are checked before the request, so concurrent or in-flight requests can slightly overshoot, and usage write failures can cause drift.
- Rejected requests (rate-limited or over quota) do not create usage records.
- Rate limiting applies only to `POST /v1/chat/completions`; `/v1/models`, health checks, and the management API are not tenant-limited.
- The PostgreSQL backend uses a single-row atomic counter and supports multiple workers; the memory backend is for local development and tests only.

## Cost, plans, and budgets

Cost is computed per request from a versioned price list and stored on the usage row.

- Prices are per million tokens: input, cached input (falls back to the input price when unset), and output. `POST /api/v1/models/{id}/prices` appends a version with an `effective_from`; changing a price never rewrites historical rows. `GET` lists versions newest first.
- Every usage row stores `list_cost` (what the traffic would cost) and `billed_cost` (what the tenant owes), plus `covered_tokens` and `billable_tokens`.
- A tenant plan is a monthly **token** allowance that resets on the 1st at 00:00 UTC and does not roll over. Tokens inside the allowance are free; the excess is priced at list price only when `plan_allow_overage` is true.
  - `plan_allow_overage=false` (default): once the allowance is used, inference returns 429 `plan_allowance_exhausted`.
  - `plan_allow_overage=true`: traffic continues, the excess is billed, and `monthly_cost_budget` (when set) returns 429 `budget_exceeded` once the billed cost reaches it.
- A tenant that has a plan or a budget but whose model has no price gets 503 `model_price_missing`. A budget that cannot be priced must not pass traffic silently; tenants without a plan or budget can still use unpriced models (cost fields stay `null`).
- The allowance is split across prompt/completion/cached buckets pro rata, so the request that crosses the boundary is not charged full price for every token.
- Enforcement reads the period total before the request and settles afterwards, so concurrent in-flight requests can overshoot by at most their own usage.

Set a price and a monthly plan:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:4000/api/v1/models/deepseek-flash/prices `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"input_per_million":"0.28","cached_input_per_million":"0.028","output_per_million":"0.42"}'

Invoke-RestMethod -Method Patch `
  -Uri http://127.0.0.1:4000/api/v1/tenants/$($tenant.id) `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"plan_tokens":1000000,"plan_allow_overage":true,"monthly_cost_budget":"50"}'
```

Read the current period:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:4000/api/v1/tenants/$($tenant.id)/billing" `
  -Headers @{ Authorization = "Bearer $master" }
```

It returns `used_tokens`, `covered_tokens`, `billable_tokens`, `list_cost`, `billed_cost`, `budget_remaining`, and the half-open `[period_start, period_end)` window. `PATCH /api/v1/tenants/{id}` accepts `plan_tokens`, `plan_allow_overage`, and `monthly_cost_budget`; an explicit `null` clears a limit.

## Tenant model access

Every tenant defaults to `mode=all`, so existing deployments need no migration step. Switch a tenant to an explicit allowlist to restrict which registered models it can call:

```powershell
Invoke-RestMethod -Method Put `
  -Uri http://127.0.0.1:4000/api/v1/tenants/$($tenant.id)/model-access `
  -Headers @{ Authorization = "Bearer $master" } `
  -ContentType "application/json" `
  -Body '{"mode":"allowlist","model_ids":["deepseek-flash"]}'
```

- `mode=all` (default) allows every enabled model; any `model_ids` in the body is ignored and cleared.
- `mode=allowlist` allows only the listed models. An empty list blocks every model without touching keys, which is a deliberate way to suspend a tenant.
- `PUT` replaces the whole set atomically. Unknown model ids return 404 `model_not_found` and nothing is applied.
- Enforcement: `POST /v1/chat/completions` returns 403 `model_not_allowed`, and `GET /v1/models` lists only the models that tenant may use. Rejected requests create no usage record.
- Read the current policy with `GET /api/v1/tenants/{id}/model-access`; tenant details also expose `model_access_mode`.

## Request audit

Request auditing is opt-in twice: set `GATEWAY_AUDIT_ENABLED=true` globally and enable `audit_enabled` for a tenant (Access 鈫?Tenants in the console, or `PATCH /api/v1/tenants/{id}`). Either switch being off means zero capture.

- Clients may send `x-llm-gateway-session-id` (1..64 chars, `[A-Za-z0-9._:-]`) to group requests. Without it, the gateway falls back to a 24-hour, 200-request prefix match scoped to the same tenant and API key; conversations that share only a system prompt are not merged.
- Requests are stored with bounded content (default 256 KiB) and deterministic turn diffs (`new_session`, `continuation`, `regeneration`, `edit`, `truncation`). Hashes and diffs use the original content, and `truncated=true` is explicit.
- Read APIs: `GET /api/v1/audit/sessions`, `GET /api/v1/audit/sessions/{id}?include_content=`, `GET /api/v1/audit/requests/{request_id}`. Master key only.
- The Audit tab shows the session timeline, bounded previews, parameter/usage/response changes, and loads full content on demand. Content is never written to browser storage or URLs.
- Audit writes are best-effort and isolated; failures log `audit_record_failed` without content and never change the inference response.

Retention cleanup, export/delete, metrics, and partitioning are not implemented yet. See [`docs/audit.md`](docs/audit.md) for enablement, privacy limits, and manual retention, and [`docs/adr/0001-request-audit.md`](docs/adr/0001-request-audit.md) for the design decision.

## Tracing

Tracing is off by default. When enabled, the gateway parses and emits W3C `traceparent` headers, records one server span per request, and one client span per upstream attempt:

- An inbound `traceparent` is honored only when well formed (version `00`, lowercase hex, non-zero ids); otherwise a new trace starts.
- Retries are sibling spans under the same request, so one logical request never becomes several unrelated traces. Each attempt carries `llm.attempt`, `llm.upstream_model`, and, for streaming, `llm.ttft_ms`.
- JSON logs carry `trace_id` and `span_id` alongside `request_id`; usage and audit rows store the same `trace_id` (`NULL` when no trace exists).
- No prompts, completions, keys, or request bodies are attached to spans.

```dotenv
GATEWAY_TRACING_ENABLED=true
GATEWAY_TRACING_ENDPOINT=http://127.0.0.1:4318/v1/traces
GATEWAY_TRACING_SAMPLE_RATIO=0.1
```

With tracing disabled nothing is recorded and no `traceparent` is sent upstream. Database spans, metrics, and tail-based sampling are not implemented yet. Design rationale: [`notes/observability.md`](notes/observability.md).

## Metrics

Metrics are off by default. When enabled, Prometheus scrapes a dedicated port (never the API port):

| Metric | Type | Labels |
|---|---|---|
| `gateway_requests` | counter | `route`, `method`, `status_code` |
| `gateway_request_duration_seconds` | histogram | `route` |
| `gateway_upstream_requests` | counter | `provider`, `model`, `status` |
| `gateway_upstream_duration_seconds` | histogram | `provider`, `model` |
| `gateway_upstream_ttft_seconds` | histogram | `provider`, `model` |
| `gateway_rejections` | counter | `reason` |
| `gateway_usage_write_failures` | counter | `reason` |
| `gateway_audit_write_failures` | counter | 鈥?|

```dotenv
GATEWAY_METRICS_ENABLED=true
GATEWAY_METRICS_HOST=127.0.0.1
GATEWAY_METRICS_PORT=9464
```

- `route` is the matched route template, never the concrete path, so ids cannot become label values. Tenant, key, request id, prompts, and completions are never labels.
- Time to first token is a histogram, not just a span attribute: a per-request value in a trace cannot be aggregated into P95.
- If the port cannot bind, the gateway logs `metrics_endpoint_bind_failed` and keeps serving traffic; it does not lose metrics silently and does not crash.
- Dashboards, alert rules, and OTLP metric export are not included.

## Configuration

| Variable | Description ||---|---|
| `GATEWAY_ENVIRONMENT` | Required. `development` / `test` / `production` |
| `GATEWAY_MASTER_KEY` | Required. Management API credential; at least 16 characters, 32 in production |
| `GATEWAY_LOG_LEVEL` | Defaults to `INFO` |
| `GATEWAY_STORAGE_BACKEND` | `memory` or `postgres` |
| `GATEWAY_DATABASE_URL` | Required for postgres, e.g. `postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway` |
| `GATEWAY_REDIS_URL` | Reserved; unused for now |
| `GATEWAY_OPENAI_API_KEY` | When empty, the OpenAI provider is not registered |
| `GATEWAY_OPENAI_BASE_URL` | Defaults to `https://api.openai.com/v1` |
| `GATEWAY_DEEPSEEK_API_KEY` | When empty, the DeepSeek provider is not registered |
| `GATEWAY_DEEPSEEK_BASE_URL` | Defaults to `https://api.deepseek.com` |
| `GATEWAY_FAKE_PROVIDER_ENABLED` | Development/test only; production forbids it |
| `GATEWAY_REQUEST_TIMEOUT_SECONDS` | Total upstream request timeout, default 60 |
| `GATEWAY_CONNECT_TIMEOUT_SECONDS` | Connect timeout, default 10 |
| `GATEWAY_MAX_RETRIES` | Max retries before the first byte, default 2 (cap 5) |
| `GATEWAY_AUDIT_ENABLED` | Global request-audit kill switch, default `false` |
| `GATEWAY_AUDIT_MAX_CONTENT_BYTES` | Per-request/response audit content budget, default 262144 |
| `GATEWAY_AUDIT_WRITE_TIMEOUT_SECONDS` | Audit write timeout; failures never affect inference, default 2 |
| `GATEWAY_TRACING_ENABLED` | W3C trace-context tracing, default `false`; when off, no spans and no `traceparent` upstream |
| `GATEWAY_TRACING_ENDPOINT` | OTLP/HTTP traces endpoint; required when tracing is enabled, e.g. `http://127.0.0.1:4318/v1/traces` |
| `GATEWAY_TRACING_SAMPLE_RATIO` | Head-based sampling ratio in `[0, 1]`, default `0.1`; an upstream decision is honored |
| `GATEWAY_TRACING_SERVICE_NAME` | `service.name` resource attribute, default `llm-gateway` |
| `GATEWAY_TRACING_EXPORT_TIMEOUT_SECONDS` | OTLP export timeout, default 5 |
| `GATEWAY_METRICS_ENABLED` | Prometheus `/metrics` endpoint on a separate port, default `false` |
| `GATEWAY_METRICS_HOST` | Metrics bind address, default `127.0.0.1` |
| `GATEWAY_METRICS_PORT` | Metrics bind port, default `9464` |
| `GATEWAY_METRICS_SERVICE_NAME` | `service.name` resource attribute, default `llm-gateway` |
| `GATEWAY_BILLING_CURRENCY` | Currency for prices and billing summaries, default `USD` |

`production` requires the `postgres` backend, disables the fake provider, and rejects placeholder or short master keys, so sample configuration cannot be deployed by accident.

## Database and migrations

Start PostgreSQL (bound to loopback only):

```powershell
docker compose up -d postgres
```

Run migrations:

```powershell
$env:GATEWAY_DATABASE_URL = "postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway"
uv run alembic upgrade head
```

Then update `.env`:

```dotenv
GATEWAY_STORAGE_BACKEND=postgres
GATEWAY_DATABASE_URL=postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway
```

Migrations only read `GATEWAY_DATABASE_URL`; they do not need the master key. The service never migrates automatically at startup, so deployments must run the migration step separately.

Redis is reserved for future rate limiting and caching and can be started with a profile:

```powershell
docker compose --profile redis up -d
```

## Docker Compose

The full stack (PostgreSQL, migrations, backend, and console) runs behind one nginx entry point:

```powershell
Copy-Item .env.docker.example .env.docker
# fill in GATEWAY_MASTER_KEY, POSTGRES_PASSWORD, and provider keys
docker compose --profile app --env-file .env.docker up -d --build
Invoke-RestMethod http://127.0.0.1:8080/healthz
```

- Console: `http://127.0.0.1:8080`
- OpenAI-compatible base URL: `http://127.0.0.1:8080/v1`
- The one-shot `migrate` service runs `alembic upgrade head` before the backend starts; a failed migration blocks the backend.
- PostgreSQL data lives in the `pgdata` volume; `down -v` deletes it.
- If port 8080 is already in use, set `GATEWAY_UI_PORT` for the Compose command (for example `$env:GATEWAY_UI_PORT='8090'`) and use that port for the console and API base URL.

See [`docs/docker.md`](docs/docker.md) for the configuration table, upgrades, backups, troubleshooting, and production hardening. Infrastructure only (backend via `uv`, console via Vite): `docker compose up -d postgres`.

## Tests and checks

```powershell
# Unit tests (no database by default)
uv run pytest

# Static checks
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

PostgreSQL integration tests are skipped by default; provide a test database to run them:

```powershell
$env:GATEWAY_TEST_DATABASE_URL = "postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway"
uv run pytest -m integration
```

Integration tests run `alembic upgrade head` and truncate tables; use a dedicated test database.

## Admin console

```powershell
cd ui
npm install
npm run dev
```

Open `http://localhost:5173`. The dev server proxies `/healthz`, `/readyz`, `/api`, and `/v1` to `http://127.0.0.1:4000`. To change the target:

```powershell
$env:VITE_PROXY_TARGET = "http://127.0.0.1:4000"
npm run dev
```

Enter the master key to view backend health, the model registry, the usage panel, and the Access tab. The Models tab provides:

- Register a model (id, provider, upstream model, enabled) with client-side validation mirroring the API; provider configuration is still a backend concern.
- Delete a model with confirmation; deleting it also removes it from every tenant allowlist.
- Manage the per-model price list: versions newest first, with an append form (prices are per million tokens and a new version applies from its effective date).
- The registry list with provider, upstream model, status, and creation time.

The usage panel provides:

- `Models / Usage / Access` tabs
- Tenant filtering (including "All tenants"); the selected tenant's quota and rate limit are shown read-only. The tenant list is capped at 100 with a truncation note.
- 7 / 30 / 90-day rolling ranges with `since` floored to UTC midnight; the final bar is the partial "today so far" bucket.
- Totals for requests, input, output, cached, and total tokens (cached counts are displayed as reported and labeled as a subset of input).
- A UTC-aligned, zero-filled daily total-token bar chart.
- Per-key usage details (up to 100 keys).

The Access tab manages tenants and API keys:

- Create tenants and edit the monthly token quota / requests-per-minute limit; empty input clears a limit.
- Set each tenant's model access policy (`All models` or an explicit allowlist) in a dedicated dialog. The dialog shows an explicit warning when an empty allowlist would block every model.
- Manage each tenant's plan (tokens, overage switch) and monthly cost budget, with the current period summary: used / covered / billable tokens, list and billed cost, and budget remaining.
- Create keys per tenant with an optional expiry. The plaintext is shown once, can be copied, and is never written to storage, the URL, or the query cache; closing an uncopied dialog asks for confirmation.
- Revoke keys with confirmation. Revoked and expired keys are labeled, and only non-revoked keys offer the revoke action.

The master key stays in page memory only; it is never written to localStorage, sessionStorage, cookies, or the URL. Disconnecting clears all admin and usage query caches.

Frontend checks:

```powershell
npm run lint
npm run typecheck
npm test
npm run format:check
npm run build
```

Build output lives in `ui/dist` and should be served by a static server on the same origin as the API. The MVP does not relax CORS; the console uses same-origin or the dev proxy.

## Error format

All errors use an OpenAI-compatible shape and include an `x-request-id` response header:

```json
{
  "error": {
    "message": "Invalid API key",
    "type": "authentication_error",
    "param": null,
    "code": "invalid_api_key",
    "request_id": "3f6c1d0e9a5b4c7e8f2a1b3c4d5e6f70"
  }
}
```

Streaming requests prefetch the first chunk before sending response headers, so upstream auth failures, timeouts, and rate limits become normal JSON errors. If an error occurs after the stream starts, the gateway emits a `data: {"error": ...}` event followed by `data: [DONE]`; the HTTP status is already 200 at that point.

## Project layout

```text
src/llm_gateway/     Backend (api, auth, providers, services, storage, schemas)
alembic/             Database migrations
tests/               pytest unit and integration tests
ui/                  React + Vite admin console
notes/               English design notes
architecture.md      LiteLLM architecture analysis
design.md            LLM-GateAway design guidance
.opencode/skills/    Repository-level Agent Skills
```

## Security

- Never commit `.env`, API keys, or the master key.
- Inference keys are stored only as SHA-256 hashes; plaintext appears only in the creation response.
- The master key is read only from the environment and cannot be used on inference endpoints; inference keys cannot access the management API.
- Logs never contain prompts, completions, Authorization headers, or full keys.
- Upstream error text is generalized before reaching clients, avoiding credential or internal-address leaks.
- PostgreSQL/Redis bind to loopback by default; production deployments belong behind a reverse proxy with TLS.

## Known limitations

- Only OpenAI, DeepSeek (OpenAI-compatible), and the fake provider are implemented; Anthropic, Bedrock, Vertex, and other non-OpenAI protocols are not.
- Each model maps to a single upstream model; no multi-deployment, weights, fallback, or cooldown.
- No invoicing, per-key or per-model budgets, or burst shaping (token bucket); quotas and budgets are soft against concurrent requests. There is no pre-call reservation by design: a tenant can overshoot by the usage of requests already in flight when the limit is crossed.
- Rate limiting uses a fixed 60-second window at tenant level only; the memory backend counts per process.
- Creating a key requires `tenant_id` (a breaking change for old callers); there is no tenant delete or rename API.
- Model access is tenant-scoped only: no per-key scoping and no per-model rate limits.
- `usage_records` has no retention or archival job and grows with traffic; cost is computed and stored per request, but there is no invoicing, no currency conversion, and no multi-currency price list.
- Tracing covers the server span and per-attempt upstream spans only: no database spans and no tail-based sampling.
- Metrics expose counters and histograms but ship without dashboards, alert rules, or OTLP metric export; database pool occupancy is not exported yet.
- A stream that disconnects before usage arrives leaves no record; write timeouts or failures only log a warning.
- Model configuration supports create, list, and delete only; changing it requires delete and recreate.
- `/v1/models` returns at most 1000 entries; the management API uses offset pagination.
- Every authenticated inference request writes `last_used_at`; high-throughput deployments should sample or batch it.
- The console cannot edit an existing model (delete and recreate instead), and the audit panel is read-only: no export/delete or retention UI, and the content budget is a global environment variable. The usage panel is read-only with daily granularity, caps keys and tenants at 100 each, and labels the final bar as today so far. Tenant delete/rename is not available.
- Local `uv` runs require a manual `alembic upgrade head`; Compose runs it through the one-shot `migrate` service, and the application process itself never migrates.

## Related documents

- `architecture.md`: LiteLLM components, request flow, and key files
- `design.md`: design principles, technology choices, and roadmap
- `notes/`: staged English design notes with trade-offs and risks
- [`docs/verification.md`](docs/verification.md): step-by-step verification for DeepSeek, tenant keys, and gateway calls
- [`docs/tenant-key-model.md`](docs/tenant-key-model.md): focused runbook for creating a tenant, API key, and model registration, with a verified DeepSeek call
- [`docs/docker.md`](docs/docker.md): Docker Compose deployment, configuration, upgrades, and backups
- [`TODO.md`](TODO.md): P2 items and the remaining P1e audit operations

## Agent skill

Repository-level skill: [`.opencode/skills/llm-gateway/SKILL.md`](.opencode/skills/llm-gateway/SKILL.md). It documents the repository map, commands, invariants, and verification workflow. Use it in place, or copy it to `~/.config/opencode/skills/` as a global skill.

## License

MIT 鈥?see [LICENSE](LICENSE).
