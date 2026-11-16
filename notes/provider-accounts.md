# Provider accounts: UI-managed upstream configuration

Working design note for ADR 0002. Scope: make provider configuration editable at runtime without
turning adapters into data and without storing secrets.

## Problem

Provider *adapters* are code. Provider *configuration* — which upstream endpoint, under which
credential, enabled or not — currently lives in `.env` plus per-deployment columns. Operators cannot
inspect or change it without a redeploy, and one adapter cannot hold several accounts unless every
deployment repeats `credential_env` and `base_url`.

Goal: move configuration into the database and admin UI. Keep adapter code, protocol translation, and
secrets where they are.

## Current state (facts the design must respect)

- `Settings` holds one credential per adapter and one default base URL per adapter.
- `build_providers()` builds `ProviderRegistry` once; `Container` is assembled once at startup.
- `ProviderRegistry` is immutable and `is_configured()` is synchronous.
- `ModelDeployment` already carries `credential_env` (a name, never a value) and `base_url`.
  `ProviderPool` caches one client per `(provider, credential_env, base_url, upstream_model-for-azure)`.
- A model with no deployments routes through `synthetic_deployment()`, which uses the model row and
  therefore the env-derived provider.
- `create_model` rejects a provider for which `is_configured()` is false.
  `create_deployment` skips that check when `credential_env` or `base_url` is set.
- `resolve_model` tolerates an unconfigured provider when a router exists, so deployments can serve
  models whose env default is absent.

So "is this provider available?" is currently answered in three places with three different rules.
A DB-backed account must collapse them into one resolver.

## Decision

Introduce `provider_accounts` as the single record for "one configured upstream", referenced from
models and deployments. Adapters stay code.

### Table

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | text, unique | operator label; appears in logs and audit |
| `adapter` | text, `ProviderName` values only | must be an implemented adapter |
| `base_url` | text, required | explicit endpoint, no implicit default |
| `credential_env` | text, required | environment variable *name*; pattern as today |
| `api_version` | text, nullable | Azure only |
| `enabled` | bool | disabling removes it from routing |
| `version` | int | incremented on every mutation |
| `created_at`, `updated_at` | timestamptz | |

Unique on `(adapter, base_url, credential_env)` to prevent silent duplicates.

### References and invariants

- `models.account_id` nullable FK; `model_deployments.account_id` nullable FK, `ON DELETE RESTRICT`.
- `account.adapter` must equal `model.provider` / `deployment.provider` when referenced (400).
  `provider` stays on those rows because it is part of `/v1/models` output and usage records.
- A deployment must not set both `account_id` and legacy `credential_env`/`base_url` (400). Mixing
  makes precedence invisible in the UI.
- `enabled=false` removes the account from routing; a model resolving only to disabled accounts
  returns `provider_not_configured` (503), not a silent fallback.

### Resolution order (first match wins)

1. `deployment.account_id`
2. `deployment.credential_env` / `base_url` (legacy, deprecated)
3. `model.account_id` (consumed by `synthetic_deployment`)
4. env/settings defaults (unchanged)

### Availability check

Replace the sync `is_configured()` call sites with an async `accounts.is_available(adapter)`: true if
the registry holds the adapter or an enabled account exists. Affected call sites: model create/update,
deployment create/update, `resolve_model`. Keep the sync registry check only where startup order
guarantees it.

### Runtime reconfiguration across workers

- `version` increments on every mutation.
- Pool cache key becomes `(account_id, version, upstream_model if the adapter needs it)`.
- Read the account row per request, joined into the existing deployment query. The database is the
  only source of truth: no pub/sub, no TTL, every worker converges immediately. The in-memory backend
  is single-process by definition.
- Client lifetime: acquire a lease per request; a stale client is closed when its last lease is
  released. Immediate `aclose()` on update is wrong — it kills in-flight streams. Shutdown keeps
  closing everything as it does today.
- Keep at most two stale clients per account; close the oldest one as soon as its lease count is zero.
  This bounds memory without touching live streams.

### Secrets

Phase 1 stores `credential_env` only. The API returns the name, never a value, plus
`credential_present` computed from the serving process environment. Audit snapshots carry no secret
by construction. Encrypted-at-rest credentials are phase 2 (G2.4) and require envelope encryption, a
master key from KMS/env, masked reads, rotation, and backup encryption.

### API and UI

- `GET/POST /api/v1/provider-accounts`, `PATCH/DELETE /api/v1/provider-accounts/{id}`.
- Reads: any admin. Writes: `require_write_access`.
- Audit actions `provider_account.created|updated|deleted`, `target_type=provider_account`, snapshots
  without secrets.
- Delete returns 409 while any model or deployment references the account.
- Optional `POST /provider-accounts/{id}/probe`: adapter-declared cheap call (`GET /models` for
  OpenAI-compatible and Anthropic) with a short timeout. Never counted as usage, never echoes the
  key, explicit timeout/rate-limit errors. Adapters without a cheap probe (Azure data plane) return
  "not supported" instead of an invented request.
- UI: list, create, edit, enable/disable, delete, probe result with timestamp. Model and deployment
  forms get an account selector; the legacy `credential_env`/`base_url` fields move behind an
  "advanced" disclosure.

### Migration

- `0020_provider_accounts`.
- Backfill: one account per distinct `(provider, credential_env, base_url)` among deployments that set
  at least one legacy field, named deterministically; then point those deployments at the account and
  null the legacy columns.
- Deployments with neither field keep using env defaults and are not backfilled: they have no row to
  reference and no operator-visible identity.
- Legacy columns stay for one release; document the deprecation window before removal.

### Failure modes

- Unknown adapter at create: 400.
- Adapter implemented but credential env empty: request-time 503 with existing error mapping;
  `credential_present=false` in the admin list makes it visible before traffic hits it.
- Account disabled mid-flight: the in-flight request keeps its lease; new requests skip it.
- Account deleted while referenced: 409.

## Tests

- Repository parity (memory vs SQL): CRUD, unique constraints, version bump, FK restrict.
- Invariants: adapter/provider mismatch, mixed legacy + account config, disabled account.
- Precedence: each of the four levels, including `synthetic_deployment`.
- Cache: version change produces a new client key; stale client stays open until its lease ends.
- Audit: every mutation recorded; snapshot contains no secret material.
- API: role checks, 409 delete protection, 400 validation.
- Integration: backfill on a real PostgreSQL instance.

## Not in scope

Runtime adapter loading, new protocols (Bedrock/Vertex), plaintext or encrypted secrets, per-tenant
BYOK, per-account rate limits or quotas.

## Open questions

- Should `usage_records`/audit metadata record `account_id`, or is the deployment name enough?
- Probe cost policy: which adapters get one, and should it be rate-limited per account?
- Which release drops the legacy deployment columns?
