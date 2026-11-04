# Tenant-scoped model access control

Status: implements TODO G0.2. Scope: backend, admin API, enforcement, and the console
(Models tab register/delete, Access tab per-tenant policy dialog).

## 1. Problem

Any tenant key could call any registered model, including the most expensive one. In an
internal multi-team deployment that is both a cost and a blast-radius problem: a team paying
for a small model can accidentally target a frontier model, and there is no way to suspend a
tenant's access to models without revoking keys.

## 2. Options considered

| Option | Why not |
|---|---|
| Per-key model scope | More flexible but multiplies configuration; keys are already per-tenant. Deferred. |
| Provider-level allowlist | Coarser than the actual risk: cost lives at the model level. |
| Single global allowlist | Cannot express "team A may use the cheap model, team B both". |
| Always default-deny | Breaks every existing deployment on upgrade, and turns a missing row into an outage. |
| Tenant allowlist with an explicit mode | Chosen. Default preserves current behavior; restriction is opt-in. |

## 3. Decision

- `tenants.model_access_mode`: `all` (default) or `allowlist`.
- `tenant_model_access(tenant_id, model_id)` holds the allowlist rows. Composite primary key,
  both foreign keys `ON DELETE CASCADE`, so deleting a model cannot leave a dangling grant.
- `mode=all` ignores and clears the row set; `mode=allowlist` with zero rows denies every
  model. An empty allowlist is therefore a supported "suspend this tenant" switch whose
  behavior is intentional, not an oversight.
- `PUT /api/v1/tenants/{id}/model-access` replaces the set atomically. Replace, not patch:
  a partially applied policy is the worst failure mode for an authorization control.
- Unknown model ids are rejected before anything is written, so a typo cannot silently widen
  or narrow access. The API returns 404 `model_not_found`; the service also pre-checks inside
  the transaction to keep memory and SQL behavior aligned.
- Reads: `GET /api/v1/tenants/{id}/model-access`. Tenant detail also carries
  `model_access_mode` for list views.

## 4. Enforcement

- `POST /v1/chat/completions`: after the model exists and is enabled, the tenant must be
  allowed. Failure is 403 `model_not_allowed` with `error_type=permission_error`.
- `GET /v1/models`: filtered to the tenant's allowed set. A tenant whose access row is gone
  (for example deleted concurrently) sees an empty list rather than an error: fail closed.
- Rejected requests create no usage record, matching the existing rate-limit behavior.
- Order matters: 404 for unknown model, 403 `model_disabled` for an operator-disabled model,
  then 403 `model_not_allowed`. This does reveal model existence to an authenticated tenant;
  accepted because model names are not secrets inside one organization. Revisit if the
  gateway ever serves mutually distrusting customers.

## 5. Trade-offs and risks

- One additional read per inference request (tenant access). It joins the existing per-request
  reads and is the same order of magnitude; caching belongs to TODO G1.3, not here.
- Policy changes take effect on the next request, with no cache to invalidate. That is a
  feature until a cache is introduced; any future cache must key on a policy version.
- No per-key scoping and no ownership checks beyond the tenant: one tenant's admin key does
  not exist yet, so all management calls still require the master key.
- The console policy dialog keeps ids that are not in the first page of the model list visible
  as "not in the loaded model list", so saving cannot silently drop a grant. A deleted model
  fails the save with 404 until it is deselected; that is deliberate rather than guessing.

## 6. Migration and compatibility

- `0007` adds the column with `server_default 'all'` and the join table. Existing tenants keep
  working unchanged, which is required for a non-breaking rollout.
- Downgrade drops the table and the column; grants are lost. That is acceptable for a
  permission table, and the note is the record of it.

## 7. References

- `src/llm_gateway/services/chat.py` (enforcement)
- `src/llm_gateway/api/admin/tenants.py` (read/replace endpoints)
- `src/llm_gateway/storage/tables.py`, `alembic/versions/0007_tenant_model_access.py`
- `tests/test_model_access.py`, `tests/test_postgres_repositories.py`
