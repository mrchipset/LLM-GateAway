# Admin UI shell: health and model registry

Status: implemented in `ui/`.

## Problem and constraints

Operators need a way to confirm the gateway is live and to inspect the model
registry without reading logs or curl output. The MVP deliberately stops there:
no key management, no chat playground, no navigation. The UI must not weaken the
security posture — the backend exposes no CORS relaxation, and the admin
credential is a long-lived shared secret.

## Assumptions

- The UI is served from the same origin as the API in production (static assets
  behind the same reverse proxy), so only relative URLs are used.
- Development uses the Vite proxy; no backend CORS middleware is added.
- `/api/v1/models` is the right source (it shows disabled models and the
  upstream mapping), which means the screen requires the master key.
- Health and readiness are public endpoints and are polled independently of the
  credential.

## Options considered

**Storing the master key in `sessionStorage` vs React state.** Session storage
survives reloads but turns any XSS into long-lived credential theft. The key
stays in React state only; a reload requires re-entry. This is the safer default
for an operator tool.

**Adding CORS for `localhost:5173` vs the Vite proxy.** A permissive CORS policy
would let arbitrary web origins call the master-key-protected API from a
browser. The dev proxy keeps the browser same-origin and leaves the backend
policy strict.

**A state-machine library vs plain TanStack Query states.** Query status plus a
small status reducer in `useBackendStatus` covers checking/healthy/degraded/
offline without another dependency.

**Dark mode by default vs a single polished light theme.** Half-implemented
dark mode is worse than none. The shell ships one complete light theme with
explicit `color-scheme: light`.

**Table only vs table plus cards.** The registry table is the right desktop
shape, but horizontal page scrolling is unacceptable on phones, so the same data
renders as stacked definition lists below `md`.

## Chosen approach

- Vite + React + TypeScript (strict) with TanStack Query, Tailwind v4 and
  locally bundled IBM Plex fonts; no component library.
- One screen: header with product name, backend version and a status card;
  a connection panel; a models panel.
- Status is text + shape + color (never color alone), announced through
  `role="status" aria-live="polite"`. Readiness 503 lists the failing checks by
  name; an unreachable backend shows an offline state with retry.
- The connection panel hides and clears the input after connecting; the
  disconnect action clears the key, cancels and removes the models query, and
  returns the panel to the connect prompt.
- Model errors surface HTTP status, `error.message`, `error.code` and
  `error.request_id`, because that request id is what an operator needs for
  server-side diagnosis.
- Timestamps are rendered in UTC with an explicit column label so tests and
  screenshots do not depend on the machine timezone.
- The empty state includes a copyable, accurate `curl` command for
  `POST /api/v1/models` instead of inventing a registration form.

## Trade-offs and risks

- The key must be re-entered after a reload; there is no "remember me".
- Only the first 100 models are shown (`limit=100`); `total` is displayed but
  there is no pagination control.
- The UI is read-only for models and does not manage API keys.
- No runtime configuration endpoint; the static build must be same-origin with
  the API, or fronted by a proxy that preserves `/healthz`, `/readyz`, `/api`.
- Clipboard copy depends on browser permissions; failure falls back to a
  selectable command.
- Health polling every 15 seconds is fixed; no backoff when the backend is down
  beyond the query's own retry behavior.

## References

- `ui/src/api/client.ts` (typed API boundary, error envelope parsing)
- `ui/src/hooks/useBackendStatus.ts`, `ui/src/hooks/useModels.ts`
- `ui/src/components/ModelsPanel.tsx`, `ConnectionPanel.tsx`, `StatusPanel.tsx`
- `src/llm_gateway/api/admin/models.py`, `schemas/admin.py`
- `design.md` section 5.4 (admin credential handling)
