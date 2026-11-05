# Console accessibility and interaction audit

## Scope and method

A source-level pass over `ui/` plus RTL behaviour tests. No browser automation was available in
this environment, and the console needs a session to render, so the review is based on the
component code and on tests that assert focus and ARIA state rather than screenshots.

Narrow-width conclusions come from the breakpoints: tables switch to cards below `md`, cards use
`minmax(0, 1fr)`, and long ids/URLs wrap, so no page-level horizontal overflow was found.

## Fixed

### Focus stays inside a dialog when its content changes

A dialog that swaps views (deployment list → create form, delete confirmation → result summary)
unmounted the focused control, so focus fell to `document.body` and keyboard navigation restarted
from the top of the page. `Modal` now restores focus to the panel after a render only when the
active element is the body or document element; it does not fight controls that are still inside
the dialog. Closing still returns focus to the trigger, and only if that trigger is still connected
(delete flows remove the row).

### Focus after a destructive action

Deleting a model or revoking a key removes the focused button when the list refetches, after the
dialog has closed. Those panels now move focus to their panel title, which is programmatically
focusable and shows a `focus-visible` ring. `PanelHeader` gained an optional `titleRef` for this.

### Async state and error announcements

- Admin audit time-range errors now set `aria-invalid`, render with `role="alert"`, and focus the
  first invalid field on submit.
- Admin edit/create/password dialogs disable every control while a request is pending, set
  `aria-busy`, and announce field errors with `role="alert"`.
- Programmatic focus targets (audit panel titles, session detail) use `focus-visible` instead of
  hiding the ring entirely; keyboard users see where focus went, mouse users do not.

### Small consistency fixes

- `Revoking...` → `Revoking…`, matching the ellipsis used elsewhere.
- Modal height uses `100dvh`, so mobile browser chrome cannot push the dialog past the viewport.
- The mobile model card list has an `aria-label` like the other panel lists.

## Deliberately not changed

- Placeholder contrast (~3.2:1) is below AA, but fixing it means changing the global muted palette;
  every field has a visible label and placeholders are non-essential hints.
- Disabled-control contrast is exempt under WCAG 1.4.3.
- Audit session rows are mouse-clickable; the keyboard path is the in-row title button, and adding
  `role="button"` to the row would create duplicate tab stops.
- Table icon buttons are ~26 px, above the WCAG 2.5.8 AA minimum of 24 px; enlarging them changes
  the table density.
- `revokeObjectURL` is called right after the download click. A delayed revocation may matter in
  some browsers, but there is no measured evidence, so it was left alone.
- Backdrop click does not close dialogs and the Tab trap uses first/last-element checks rather than
  background `inert`. That is the existing contract; changing it is a behavioural redesign.

## Verification

Three new tests and four extended ones assert the focus/ARIA behaviour. Mutation check: reverting
the modal focus fallback, the two title focus moves, or the audit field focus made the new
assertions fail (`4 failed`), confirming the tests guard behaviour rather than markup.

`npm run lint`, `typecheck`, `test` (167), `format:check`, and `build` all pass. The existing
chunk-size warning is unchanged.
