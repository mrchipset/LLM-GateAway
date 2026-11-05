# Tenant delete + model capabilities in the admin console

## Problem

The backend added three behaviours that the console did not expose:

- tenant rename through `PATCH /api/v1/tenants/{id}` (`409 duplicate_tenant`)
- owner-only soft delete through `DELETE /api/v1/tenants/{id}` (tenant hidden, keys revoked,
  usage and audit history preserved)
- model capability edits through `PATCH /api/v1/models/{id}` (`context_window`,
  `max_output_tokens`, `supports_tools`, `supports_streaming`; explicit `null` clears numbers)

## Decisions

- Reuse the existing tenant edit dialog instead of adding a second dialog. It now edits the name,
  limits, audit collection, and owns the delete confirmation. The heading changed from
  "Edit tenant limits" to "Edit tenant" because the dialog covers more than limits.
- Rename is validated client-side with the same helper as tenant creation (trimmed, 1..100). The
  `name` field is only added to the PATCH body when the trimmed value differs from the original.
- Deletion is a two-step inline confirmation. The warning is in Chinese because it describes an
  irreversible-looking operator action: the tenant disappears from the console, every key is
  revoked, usage and audit history remain, and there is no console undo.
- Use a new `canManageTenants` capability (owner only) instead of reusing `canDeleteAudit`. The
  backend requires the owner role, while operators still need write access for rename/limits.
- After delete succeeds, `useDeleteTenant` invalidates the tenant and key query prefixes. The key
  invalidation predicate skips the key page whose filter is the deleted tenant, so it cannot
  refetch and surface a 404.
- The API key filter and page offset are controlled by `AccessPanel`, which is the shared parent of
  the tenant and key panels. Its delete handler resets both when the filter matches the deleted
  tenant, then forwards the event to `Workspace` so the usage tenant selection is cleared too.
  This keeps the deletion reaction in one callback chain instead of adding effects or refs.
- When the deleted tenant was the only row on a non-zero tenant page, `TenantsPanel` moves the
  offset back one page in the same delete handler. A non-empty page keeps its offset, and an empty
  first page falls through to the normal empty state.
- Model capability patches follow the existing partial-update pattern: dirty numbers are parsed
  with `parseCountChange` (blank becomes `null`), and toggles are sent only when they changed.
  Missing capability flags default to `true`, matching the backend defaults.

## Trade-offs

- The delete confirmation requires two clicks, not typing the tenant name. This matches the
  existing revoke/delete dialogs in the console.
- Moving the key filter/offset into `AccessPanel` makes `KeysPanel` controlled. That is more
  wiring, but it is what lets a delete reset the filter synchronously before the query remounts.
