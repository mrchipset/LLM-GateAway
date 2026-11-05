# Model edit dialog: provider and upstream editing

Status: implemented in `ui/`.

## Problem and constraints

`PATCH /api/v1/models/{model_id}` accepts `provider` and `upstream_model`, but
the console showed both as read-only. Operators had to delete and re-register a
model to fix a typo in the upstream name, which also dropped its limits and
pricing. The dialog must not diverge from the create dialog's validation style,
must stay usable on mobile, and must not restyle the existing form.

The backend refuses routing changes with `409 model_has_deployments` when the
model has deployments, because a deployment overrides the model defaults. That
is not an error the UI can prevent, so it has to be explained before the
operator hits save and surfaced clearly afterwards.

## Chosen approach

- Two editable fields, provider as a `select` over `MODEL_PROVIDERS` and
  upstream as a trimmed text input, reusing the create dialog markup and
  classes. One section heading (`Routing`) keeps the existing visual rhythm.
- Upstream validation is extracted into `validateUpstreamModel` and reused by
  `validateModelDraft`, so create and edit cannot drift.
- The patch stays partial: only dirty fields are sent. Upstream dirtiness
  compares trimmed values, so whitespace-only edits do not produce a request.
- The 409 rule is stated once, inline above the fields, and a shorter
  deployment-dialog hint appears only when the mutation fails with
  `model_has_deployments`. The dialog stays open and keeps the typed values;
  navigation is never automatic because deleting deployments is a separate,
  deliberate action in the Deployments dialog.

## Trade-offs and rejected options

- **Hiding the fields when deployments exist.** It would need an extra
  deployments request per dialog open, and would hide the current values from an
  operator who is about to delete the deployments.
- **Detecting deployments client-side and blocking submit.** Same extra request,
  plus a race: deployments can be created between the check and the save. The
  server owns the rule.
- **Resetting the form on 409.** Destroying the operator's input after a
  recoverable conflict is worse than keeping it.

## Risks

The inline explanation is Chinese while the surrounding labels stay English,
matching the existing Chinese capability hints in the create dialog. If the
console is localised later, these two strings move with the rest.
