# Admin console: limits, deployments, and audit export/delete

Context: the backend already exposes tenant/key/model limits, model deployments, and audit
export/delete. This change closes those gaps in `ui/` only.

## Decisions

- Limit fields on response models are optional in TypeScript and validated leniently when absent
  (`undefined` is treated as "not configured"). Existing console fixtures and older responses keep
  working; a present value is still validated (`>= 1` for rate/concurrency, `>= 0` for retention).
- Retention is shown as `Inherit` (null), `Hold` (0), or `Nd`. The edit and create forms state the
  same rule inline in Chinese, as requested.
- Deployment writes live in a dialog opened from the model row. Create sends the full payload;
  edit sends only changed fields, and explicitly sends `null` to clear `credential_env` or
  `base_url` (the PATCH contract distinguishes omitted from null).
- The deployments dialog never has a secret field. `credential_env` is labelled as a variable name
  and constrained to `^[A-Z][A-Z0-9_]*$`.
- Audit export uses the admin fetch wrapper (session cookie, CSRF not needed for GET), reads the
  streamed `Blob`, takes the filename from `Content-Disposition`, and revokes the object URL after
  the download. Nothing is written to `localStorage` or `sessionStorage`.
- Audit deletion is a two-step state machine: a dry run stores the exact cutoff it previewed, and
  the destructive button is only enabled while the form still matches that cutoff. Changing the
  tenant or cutoff clears the preview, so a stale count cannot authorize a different deletion.
- Role gates mirror the backend: write controls for owner/operator, audit export for owner/auditor,
  audit delete for owner only (`canDeleteAudit`).
- `testTimeout` is 10s. The heaviest tenant-pagination test already takes ~3.6s alone and exceeded
  the 5s default once the suite ran fully parallel in this environment.

## Trade-offs

- Optional response fields are slightly weaker than a required contract, but keep the console
  compatible with a backend that has not yet shipped the fields.
- The deployment editor covers weight, enabled, upstream model, credential variable, and base URL;
  it intentionally does not edit provider or name because the PATCH contract does not support them.
- Deployment writes are hidden from auditors even though GET is allowed, matching how the rest of
  the registry actions are gated.
