# Tenancy: organizational ownership for API keys

Status: implemented in `storage/`, `auth/keys.py`, `api/admin/tenants.py`, and
migration `0002`.

## Problem and constraints

Operators asked for multi-tenant key generation and per-tenant usage. The
original MVP explicitly excluded tenant organizations, SSO, and RBAC, so the
question was how much tenancy to add without inventing an identity system.
Every request must be attributable to a tenant and a key, and the change must
work for both storage backends and survive the existing PostgreSQL data.

## Assumptions

- A tenant is an organizational label with a stable id and a unique name. It is
  not an identity: there is no tenant login, tenant-scoped admin credential,
  quota, or billing account.
- The master key remains the only control-plane credential. Tenant operators do
  not get access to the management API.
- Every API key belongs to exactly one tenant. One key cannot be shared across
  tenants; a caller that needs two tenants gets two keys.
- Existing keys must not be lost: migration `0002` assigns them to a `default`
  tenant rather than leaving them unattributed or rejecting startup.

## Options considered

**A free-text `tenant` column on keys.** No stable identifier, no tenant list,
no duplicate protection, and usage aggregation would rely on strings. Rejected.

**A full tenant system with separate admin users, RBAC, and quotas.** This is a
different product phase (identity, invitations, roles, billing). It would
require new authentication paths and dwarf the usage feature. Rejected for this
round.

**Optional `tenant_id` with implicit "default".** This keeps the old API
working but silently hides attribution mistakes and makes per-tenant reporting
ambiguous. A required field plus a migration backfill is explicit and
recoverable. Chosen.

**Tenant table + foreign key, master-key-only management.** Minimal model that
supports listing, validation, and joins for usage. Chosen.

## Chosen approach

- `tenants(id uuid pk, name varchar(100) unique, created_at timestamptz)`.
- `api_keys.tenant_id` is `NOT NULL` with `ON DELETE RESTRICT`. There is no
  tenant delete endpoint; a future delete must decide what happens to keys and
  usage first, and RESTRICT makes that explicit instead of cascading history.
- Migration `0002` inserts a fixed default tenant
  (`00000000-0000-0000-0000-000000000001`, name `default`), adds the column,
  backfills, then applies `NOT NULL`, the FK, and the index. The fixed UUID
  makes the migration idempotent and lets operators locate the backfilled keys.
- `POST /api/v1/keys` requires `tenant_id` and validates that the tenant exists
  (404 `tenant_not_found`). A concurrent delete between validation and insert is
  mapped from FK violation `23503` to the same 404 instead of a 500.
- `GET /api/v1/keys?tenant_id=` filters in the repository before pagination and
  count, echoes the filter in the response, and returns 404 for an unknown
  tenant rather than an empty page (a mistyped UUID should not look like "this
  tenant has no keys").
- Tenant names are case-sensitive and unique. Memory and SQL implementations
  both reject duplicate names and duplicate ids, so tests and development do not
  diverge from PostgreSQL.

## Trade-offs and risks

- **Breaking API change**: key creation without `tenant_id` now returns 400.
  This is documented in the README; there is no compatibility window because the
  project has no external consumers yet.
- There is no tenant update, delete, suspend, or rename API. Names are immutable
  for now.
- Tenants provide attribution, not isolation: any valid key can call any enabled
  model. Model allow-lists per tenant are a separate feature.
- No quotas or rate limits per tenant; usage accounting is observability, not
  enforcement.
- Migration downgrade drops tenant attribution (the column cannot be
  reconstructed). That is an accepted cost of downgrading.
- The default tenant is a migration artifact. Operators may rename tenants only
  by recreating them, so the default name persists.

## References

- `src/llm_gateway/storage/repositories.py` (Tenant, repository contracts)
- `src/llm_gateway/api/admin/tenants.py`, `api/admin/keys.py`
- `alembic/versions/0002_tenant_scoped_keys.py`
- `notes/admin-api.md`, `notes/postgres-persistence.md`
