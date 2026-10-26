---
name: llm-gateway
description: Develop and operate LLM-GateAway, a self-hosted OpenAI-compatible LLM gateway. Use when adding or changing providers, inference or admin APIs, tenant API keys, quotas, rate limiting, token usage accounting, PostgreSQL schema/migrations, or the React admin console.
---

# LLM-GateAway

## Use this skill when

- Adding or changing a provider adapter, model routing, or streaming behavior.
- Touching `/v1/*` inference, `/api/v1/*` management APIs, auth, tenancy, quotas, or usage accounting.
- Changing storage, migrations, the admin console, or the verification workflow.

## Repository map

- `src/llm_gateway/app.py` — app factory and router wiring; `config.py` — frozen settings; `container.py` — dependency container; `errors.py` — OpenAI-compatible error envelope; `request_context.py` — request id + access logs.
- `providers/` — `ChatProvider` protocol, OpenAI-compatible and fake adapters, registry, retry policy.
- `auth/` — hashed key generation and the inference/master-key dependencies.
- `services/chat.py` — model resolution, first-chunk prefetch, stream lifecycle; `services/usage.py` — token normalization and best-effort recording; `services/limits.py` — quota and rate-limit enforcement.
- `storage/` — repository protocols, in-memory and SQLAlchemy implementations, fixed-window rate limiter, tenant/usage domain records.
- `api/inference.py`, `api/admin/*` — transport layers; `alembic/` — additive migrations; `tests/` — unit and PostgreSQL integration tests; `ui/` — React console; `notes/` — design decisions.

## Golden commands (PowerShell 7)

```powershell
uv sync
Copy-Item .env.example .env          # replace GATEWAY_MASTER_KEY; enable the fake provider for local demos
uv run uvicorn llm_gateway.app:create_app --factory --reload --port 4000

uv run pytest                        # unit tests, no database
$env:GATEWAY_TEST_DATABASE_URL = "postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway"
uv run pytest -m integration         # uses a real PostgreSQL and truncates tables
uv run ruff check .
uv run ruff format --check .
uv run pyright

docker compose up -d postgres
docker compose --profile app --env-file .env.docker up -d --build   # full stack: UI + API on :8080
$env:GATEWAY_DATABASE_URL = "postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway"
uv run alembic upgrade head

cd ui
npm install
npm run dev                          # proxies /healthz,/readyz,/api,/v1 to :4000
npm run lint; npm run typecheck; npm test; npm run format:check; npm run build
```

## Invariants

- Inference stays OpenAI-compatible. Management APIs live under `/api/v1` and accept only the master key; inference keys cannot call them, and the master key cannot call inference.
- Every error uses the envelope `{"error": {message, type, param, code, request_id}}` plus `x-request-id`; validation failures are 400, not 422.
- Provider details stay inside adapters. Routing and services depend only on `ChatProvider` and the registry. Streams are async generators and must be released on success, error, and disconnect.
- Streams prefetch the first chunk so upstream failures become real JSON errors; failures after the first byte become an SSE error frame followed by `[DONE]`.
- Keys are stored as SHA-256 hashes; plaintext is returned once. Usage records `cached_tokens` are a subset of `prompt_tokens`; quotas are soft pre-request checks.
- Settings are fail-closed: `GATEWAY_ENVIRONMENT` is required; production requires PostgreSQL and rejects the fake provider and placeholder keys.
- Public boundaries are typed; dependencies are injected through `Container`; do not swallow exceptions or introduce provider branches in core flow.
- Migrations are additive; never edit an applied revision. Schema changes update protocols, memory, SQL, `Container`, and both unit + integration tests.
- Tests describe behavior and fail when it breaks. Non-trivial decisions need an English note under `notes/`. Use Conventional Commits and do not add AI attribution.

## Recipes

### Add an OpenAI-compatible provider

1. Add a `ProviderName` member.
2. Add `Settings` fields (API key + base URL); update `.env.example`.
3. Register it in `providers/factory.py` through the shared OpenAI-compatible helper.
4. Test registry wiring, base URL/auth, and an end-to-end completion with `respx`.
5. Register models through `POST /api/v1/models` with the new provider name.

### Add a non-OpenAI protocol

Implement `ChatProvider.complete`, `.stream`, and `.aclose`; translate requests/responses into the typed schemas and map failures to the provider error hierarchy. Register it in the factory. Do not change the inference routes, auth, storage, or UI.

### Change storage or schema

Update the protocol in `storage/repositories.py` first, then the memory and SQL implementations, `tables.py`, a new Alembic revision, and `Container` wiring. Add unit tests for memory semantics and marked integration tests for SQL. Run `alembic upgrade head` against the test database.

### Change usage or quotas

Keep filters half-open (`[since, until)`), UTC-aligned buckets, dense zero-filled series at the API layer, and `cached_tokens` normalization (OpenAI `prompt_tokens_details.cached_tokens`, DeepSeek `prompt_cache_hit_tokens`). Quotas use the UTC calendar month and reported `total_tokens`; rate limits use a fixed 60-second window with a single atomic PostgreSQL upsert. Update the summary/by-key/series and enforcement tests together.

### Change the console

Route visual decisions through the designer workflow. Extend `ui/src/api/client.ts` with a validating parser, add hooks whose query keys never include the master key, and keep the credential in React state only. Cover loading, empty, error (status/code/request id), and responsive states, then run all UI checks.

## Verification

1. Run the targeted tests for the touched module.
2. Run `uv run pytest -q`; add `-m integration` with `GATEWAY_TEST_DATABASE_URL` when SQL or migrations changed.
3. Run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright`.
4. For UI changes, run lint, typecheck, tests, format check, and build from `ui/`.
5. Confirm `git status` is clean of artifacts, secrets, `.env`, and generated files.

For a copy-paste operator check (DeepSeek key, tenant key, streaming, usage), follow
`docs/verification.md`.

## Pitfalls

- `.env.example` placeholders are rejected; generate a random master key.
- Fake models require `GATEWAY_FAKE_PROVIDER_ENABLED=true`, which production forbids.
- Migrations only read `GATEWAY_DATABASE_URL`; they are never run automatically at startup.
- Integration tests truncate tables and run Alembic; never point them at a real database.
- Alembic's internal event loop cannot nest inside pytest-asyncio; existing tests call migrations via `asyncio.to_thread`.
- PowerShell aliases `curl` to `Invoke-WebRequest`; use `curl.exe` for streaming examples.
- DeepSeek model ids change over time and live in the registry, not in code; `reasoning_content` must round-trip in tool loops.
- Do not add backend CORS. The console uses same-origin or the Vite proxy.
