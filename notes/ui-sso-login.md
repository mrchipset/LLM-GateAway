# SSO entry point on the console login screen

## Problem

The backend now runs an OIDC authorization-code flow, but the console had no way to start it. The
login screen must offer SSO without weakening the existing password login, session cookie, or CSRF
contract.

## Decision

- **A real navigation, not a fetch.** The SSO control is an `<a href="/api/v1/auth/oidc/start">`.
  The browser has to follow the redirect to the identity provider and come back through the
  callback, so `fetch` would break the flow and lose the redirect.
- **Link styled as a secondary button.** `buttonClassName` moved out of `Button.tsx` into
  `buttonStyles.ts` so the anchor and the real buttons share one set of class strings; no second
  button component and no `as`/`href` prop on `Button`.
- **Best-effort status probe.** `GET /api/v1/auth/oidc/status` is public, so `getOidcStatus` uses
  the plain `send` path instead of `sendAdmin`: a 401 here must not trigger the "session expired"
  reset. The probe starts hidden and only turns the link on when it resolves with
  `enabled: true`; a failure leaves the password form as the only path, which is the desired
  fallback rather than an error state.
- **Error banner from the URL.** The callback reports failures as `/?sso_error=<code>`. Codes map to
  short, non-technical sentences; unknown codes get one generic sentence. The code is read once on
  mount and removed with `history.replaceState`, so a refresh does not replay the banner and no
  storage is involved.
- **Password form stays primary.** The form is unchanged and keeps initial focus; the SSO link sits
  below it behind a small "or" divider.

## Rejected

- `useQuery` for the status probe: a local effect is enough for a one-shot public read and avoids
  adding a cache key that would have to be excluded from admin invalidation.
- `window.location.assign` on a `<button>`: an anchor is keyboard- and middle-click friendly and
  needs no JavaScript.
- Reloading after reading `sso_error`: unnecessary, and it would discard what the user typed.

## Trade-offs

- The divider appears only once the probe confirms SSO is available, so password-only users never
  see an empty gap in the panel.
- A stale `sso_error` carried by a shared link is cleared on load, so the message cannot be passed
  on as a link.

See `notes/oidc.md` for the server-side flow.
