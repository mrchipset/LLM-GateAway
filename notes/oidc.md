# Admin SSO with OIDC

## Problem

Admin access was local-password only. Organizations that run an identity provider need console
login through it, without turning the gateway into an identity broker and without weakening the
existing session, CSRF, and role model.

## Decision

### Authorization-code flow with PKCE, exchanged server-side

The browser is redirected to the provider's `authorization_endpoint` with `state`, `nonce`,
`code_challenge` (S256), and the configured scopes. The code is exchanged **server-side** with the
client secret, and the ID token is validated against the provider's JWKS.

- `state`, `nonce`, and `code_verifier` live in short-lived HttpOnly cookies scoped to
  `/api/v1/auth/oidc`, `SameSite=Lax`, and `Secure` in production. They are cleared on every
  callback outcome, success or failure.
- The browser never receives the client secret, the ID token, or the access token.
- Allowed signing algorithms are an explicit allowlist (RSA/PS/EC); `none` and HMAC are rejected.
- Discovery and JWKS are cached for an hour; a previously unseen `kid` triggers a refetch.
- There is no refresh token and no token storage: the gateway session is the only credential.

Rejected: implicit flow (tokens in URLs), front-channel code exchange (secret in the browser), and
keeping the provider's access token for later API calls. None are needed to authenticate an admin.

### Identity linking is by `sub`, never by username

`admin_users.oidc_subject` is unique when set. A matching `preferred_username` does **not** take over
an existing local account: otherwise an IdP user named `owner` could inherit a local owner.
Local accounts stay local; OIDC identities are separate rows.

### Roles come from a configured claim, with a deterministic precedence

`oidc_role_claim` (default `groups`) may be a string or a list. `oidc_role_map` maps claim values to
`owner`/`operator`/`auditor`; if several map, `owner` wins over `operator` over `auditor`. No
mapping means no login (`role_not_mapped`), not a default role.

### JIT provisioning is opt-in

With `oidc_jit_provisioning=true`, the first successful login creates an active admin with the
mapped role, a random unusable password hash, and the provider subject. With it disabled, an
operator must provision the identity first (there is no admin UI for setting a subject yet, so the
practical flow is JIT or a manual database seed).

Provisioning tries `preferred_username` and falls back to a deterministic `oidc-<hash(sub)` when the
name collides. Roles of existing OIDC admins are not overwritten on later logins: local role changes
are authoritative after provisioning.

## Consequences

- Password login, the master key, sessions, CSRF, and RBAC are unchanged; OIDC only creates a
  session.
- The callback redirects to `/?sso_error=<code>` on failure so the console can show a message
  without a JSON error page. State mismatch is the one error returned as a 400, because it means the
  flow was tampered with or the cookie expired.
- Logout is local-only; the provider session is not terminated (no RP-initiated logout).

## Gaps

- No refresh or group sync: role changes require a new login (and are not applied to existing OIDC
  admins at all, by decision).
- No admin UI to inspect or unlink `oidc_subject`; deleting the admin row is the only removal.
- Single provider per deployment; no per-tenant IdP or multi-issuer discovery.
- No back-channel logout or SCIM.
