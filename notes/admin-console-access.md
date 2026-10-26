# Admin console access management

Status: implemented in `ui/src/components/{AccessPanel,KeysPanel,TenantsPanel,...}`.

## Problem and constraints

The console could only show health, models, and usage; tenants and API keys were
managed with curl. The backend already exposed `/api/v1/tenants` and
`/api/v1/keys`, so this work was UI-only. The hard constraints were secret
handling and tenancy correctness:

- the master key stays in React state and never reaches storage, URLs, or logs;
- an inference key's plaintext is shown exactly once and cannot be retrieved;
- `PATCH /tenants/{id}` distinguishes omitted fields (unchanged) from explicit
  `null` (clear), and values must be >= 1;
- duplicate tenant names are 409, unknown tenants are 404, and a revoked key
  returns 401;
- the console is same-origin through nginx/Vite, with no CORS relaxation.

## Options considered

**Separate routes/pages vs an Access tab.** A router would add history and
navigation for two related sections. An Access tab next to Models/Usage keeps
the single-screen console and lets tenant and key management share the tenant
list and visual language.

**Client-side validation only vs server-first.** The UI validates names, tenant
selection, positive limits, and future expiry before sending, but always renders
the server envelope (`code`, `request_id`) and keeps the form state on failure.
The server remains the authority (secret, hash, clock).

**A dedicated secret route vs an in-memory modal.** There is no secret route:
the response is moved into component state, the create mutation is reset and
removed from the mutation cache, and the modal renders the value once. No
storage, URL, query key, or query cache contains it.

**A table-only key list vs merged two-line cells.** Eight narrow columns
collided at the console's content width (the status badge overlapped Last used).
The desktop table now uses six columns with two-line cells (key+prefix,
tenant+id, status+last used), while mobile keeps cards.

**`dataUpdatedAt` as the status clock vs a live tick.** Using the response time
alone leaves an expiring key "Active" until a refetch. A 60-second tick updates
the displayed status; `dataUpdatedAt` remains only the initial fallback and the
"Updated ..." label.

## Chosen approach

- `AccessPanel` hosts `TenantsPanel` and `KeysPanel`; both are gated by the
  master key and render connect prompts when disconnected.
- Tenant create/edit use typed client functions and mutations that invalidate
  the shared `['admin-tenants']` prefix, so the usage selector and read-only
  limits refresh together.
- Limit editing sends only dirty fields and shows a "Will clear" notice; an
  empty input becomes an explicit `null`.
- The key list is tenant-filtered and paginated; status is `Revoked` first, then
  `Expired` if the expiry passed, then `Active`. The revoke action is only
  offered for non-revoked keys.
- Key creation validates tenant/name/expiry, converts the browser-local
  `datetime-local` value to an ISO UTC string, and shows a one-time secret modal
  with copy feedback. Closing an uncopied secret asks for confirmation; closing
  a copied one is immediate. Disconnect unmounts the panel and discards the
  secret and key queries.
- A shared `Modal` provides focus trap/return, Escape handling, body scroll
  locking, and a configurable `closeDisabled` (used only for pending writes, not
  for the secret dialog).
- Admin query keys/prefixes live in `lib/queryKeys.ts`; App's disconnect cleanup
  is derived from that list, including `admin-keys` and `usage-by-key`.

## Trade-offs and risks

- There is no tenant delete or rename API; test tenants created in a browser
  must be removed directly from the database. Tenant delete is deferred to P2.
- Tenant selectors fetch at most 100 tenants; both Access and Usage surface the
  cap instead of silently hiding tenants.
- The status clock ticks every 60 seconds, so an expiry can appear up to a minute
  late; server-side auth is always authoritative.
- Clipboard access can fail in automated or restricted browsers; the dialog
  keeps the key visible with a "copy manually" instruction.
- `datetime-local` depends on the browser clock/timezone; the payload is always
  converted to UTC, and the server rejects past expiry.
- The plaintext exists briefly in React state and the DOM while the dialog is
  open; tests assert it is absent from storage, query/mutation caches, and the
  DOM after close/disconnect.

## Verification

- 85 Vitest/Testing Library tests cover tenant create/edit, pagination, limit
  dirty/null semantics, key create/expiry/validation, one-time secret lifecycle,
  copy success/failure, revoke, tenant filtering, disconnect cleanup, status
  precedence, and the 100-tenant note.
- Real-browser Playwright run against the Docker stack: connect with the
  configured master key, create a tenant, set/clear limits, create a key, copy
  it, call `/v1/models` (200), close the dialog, verify no key in the DOM or
  browser storage, revoke, and call again (401). The test tenant/key were then
  removed with SQL because no tenant-delete API exists.

## References

- `ui/src/components/{AccessPanel,TenantsPanel,KeysPanel,KeyCreateDialog,KeySecretDialog,KeyRevokeDialog,KeysTable,Modal}.tsx`
- `ui/src/hooks/{useTenants,useTenantMutations,useKeys,useKeyMutations}.ts`
- `ui/src/lib/{queryKeys,keys}.ts`
- `ui/src/test/{App.access.test.tsx,App.keys.test.tsx,App.queryKeys.test.tsx}`
- `src/llm_gateway/api/admin/{tenants,keys}.py`, `schemas/admin.py`
- `TODO.md` P0, `notes/usage-console.md`
