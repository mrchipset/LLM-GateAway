# Management API: keys and model registry

Status: implemented in `src/llm_gateway/{schemas/admin.py,api/admin/}`.

## Problem and constraints

The control plane must let an operator create, inspect, and revoke inference
keys and register models without touching the database. `AGENTS.md` requires a
path prefix and authentication separate from inference, stable error codes,
hashed key storage, and pagination on list endpoints. The MVP has no user or
team model, so there is exactly one administrative credential.

## Assumptions

- Operators hold the master key out of band (environment or secret manager) and
  never send it from a browser session; the admin UI is treated as a local tool.
- One model name maps to one provider deployment; there is no update endpoint
  because delete-and-recreate is the intended workflow at this stage.
- A returned plaintext key is acceptable exactly once, at creation time, with
  the operator responsible for storing it.

## Options considered

**Dedicated admin service layer vs thin handlers over repositories.** The admin
routes only hash a new key, validate a provider, translate duplicate/not-found
results, and map records to response schemas. A service layer would add an
indirection with no behavior; handlers stay thin and typed.

**`DELETE /keys/{id}` vs `POST /keys/{id}/revoke`.** Revocation is expressed as
DELETE because the resource has no other mutation. It is deliberately not
idempotent: revoking an already-revoked key returns 404, matching "not found or
already revoked" and avoiding a misleading success.

**Validating the provider when creating a model vs at request time.** Failing at
creation gives the operator immediate feedback. The request path still returns
503 `provider_not_configured` defensively, because configuration can change
between deployment and request.

**Returning metadata-only lists vs full records.** Lists expose `key_prefix`,
timestamps, and state. The hash and plaintext never leave the store. This makes
the list safe to show in a UI.

## Chosen approach

- `/api/v1/keys` and `/api/v1/models` require `require_master_key` at the router
  level; inference keys and the master key cannot cross endpoints in either
  direction.
- Key creation validates a future `expires_at`, generates the secret with
  `secrets.token_urlsafe`, persists only the SHA-256 hash and display prefix,
  and returns the secret once.
- Lists use `limit` (1..100, default 50) and `offset`, with `total` from the
  repository. Ordering is delegated to the repository so memory and SQL share
  one behavior.
- Model creation validates the provider against the configured registry (400
  `provider_not_configured`), returns 409 `duplicate_model` on conflict, and
  lists include disabled models.
- Deletes return 204 with no body; missing resources return 404 with stable
  codes `key_not_found` / `model_not_found`.

## Trade-offs and risks

- No audit log of administrative actions yet; this is required before multi-user
  operation and is recorded as a follow-up.
- A single static master key means no per-operator attribution or rotation.
- There is no model update endpoint; changing `upstream_model` requires delete
  and recreate, which briefly makes the model unavailable.
- No idempotency keys on create; a retried create can produce two keys.
- Pagination is offset-based, which is fine for operator-scale lists.

## References

- `src/llm_gateway/api/admin/keys.py`, `api/admin/models.py`
- `src/llm_gateway/schemas/admin.py`
- `src/llm_gateway/auth/keys.py`, `auth/dependencies.py`
- `design.md` sections 4.7, 4.8
