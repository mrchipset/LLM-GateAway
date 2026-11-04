# Management-plane identity, roles, and admin audit

Status: implements TODO G0.1 and G0.3. Scope: backend, admin API, and the console
(login, role-aware navigation, Admins and Admin audit panels).

## 1. Problem

Every management action required one static master key. There was no actor, no least
privilege, and no way to answer "who changed this tenant's budget". With billing and model
ACLs now in the management plane, that is a review blocker, not a convenience gap.

## 2. Decisions

### 2.1 Local accounts, three roles

`admin_users` holds a username (lowercase), display name, role, password hash, active flag,
and timestamps.

| Role | Read admin data | Write config | Manage admins | Read audit |
|---|---|---|---|---|
| owner | yes | yes | yes | yes |
| operator | yes | yes | no | no |
| auditor | yes | no | no | yes |

`owner` is the only role that can create or change admins. `operator` covers day-to-day
tenants, keys, models, prices, plans, and ACLs. `auditor` is read-only and is the only
non-owner role that can read the admin audit trail.

Why not more roles: a matrix with per-resource permissions is a product in itself; three
roles cover the actual job separation (operate vs review vs own). Route-level checks match
this table one-to-one, so an audit of "what can this role do" is a single grep.

### 2.2 Passwords: stdlib scrypt

`scrypt$n$r$p$salt$hash` with n=2^14, r=8, p=1, 32-byte key, per-password salt. Parameters
are stored with each hash, so they can be raised later without invalidating existing
passwords. No new dependency for a security-critical primitive.

Unknown usernames still pay a dummy verification so response time does not reveal whether an
account exists.

### 2.3 Sessions: opaque token, hashed at rest

Login creates a random 256-bit token. Only its SHA-256 is stored. The token travels in an
`HttpOnly`, `SameSite=Lax` cookie (`Secure` in production), with a configurable TTL (default
12h). Logout revokes the row, so revocation is immediate and does not wait for expiry.

Why not JWT: revocation and "password changed" semantics are the requirement, and an opaque
row is simpler than a denylist.

### 2.4 CSRF: double submit

A second cookie `gw_admin_csrf` is readable by the console. State-changing requests
authenticated by a session must send the same value in `x-csrf-token`; the server compares
`sha256(header)` to the stored hash. A cross-site form cannot set a custom header, and
`SameSite=Lax` already blocks the cookie on cross-site POSTs.

Master-key callers are exempt: the credential is not ambient, so there is nothing to forge.

### 2.5 Break-glass master key

`GATEWAY_MASTER_KEY` still authenticates every management route and maps to the `owner`
role, because that is exactly what it meant before identities existed. `master_key_enabled`
can turn it off. If it is off and no active owner exists, startup fails instead of bringing
up a management plane nobody can enter.

This keeps every existing script and the current console working during the migration, and
gives operators an escape hatch if the admin table is wrong.

### 2.6 Bootstrap

`bootstrap_admin_username` + `bootstrap_admin_password` create one owner at startup when no
active owner exists. It never resets a password and never overrides an installation that
already has an owner, so leaving the variables set is harmless. The password is hashed at
rest and never logged.

### 2.7 Login throttling

Five failed attempts per username per 15 minutes, counted in PostgreSQL with the same
single-row upsert pattern as tenant rate limiting, so it is shared across workers. A
successful login clears the counter.

This is per-username only. A distributed attacker can still spread attempts across
usernames; per-IP throttling needs the edge proxy and is left there.

### 2.8 Admin audit

`admin_audit_events` records actor type (`admin` / `master` / `bootstrap`), actor id and
name, action (`tenant.updated`, `api_key.revoked`, ...), target type and id, before/after
business fields, request id, and timestamp.

Rules:

- Metadata only. No passwords, hashes, session tokens, key plaintext, or key hashes. Snapshot
  helpers live in one module (`services/admin_audit.py`) so this is enforceable by review.
- Writes are best effort: the action already happened, so failing the response would
  misreport it. Failures increment `gateway_admin_audit_write_failures` and log, and the gap
  is documented rather than silent.
- Read access: owner and auditor. Operators cannot read the trail; they can still see their
  own effects in the resources they manage.

Actions covered in this pass: admin create/update, tenant create/update, tenant model access
replace, API key create/revoke, model create/delete, price version create, and bootstrap.

## 3. Consequences

Positive:

- every management action now has an actor and a diff;
- least privilege is real: a read-only reviewer cannot change a budget;
- sessions can be revoked instantly, including on password change;
- the master key can be retired without breaking API automation.

Negative / accepted:

- two credentials to reason about during the transition (cookie vs master key);
- CSRF only protects cookie-authenticated calls, by design;
- login throttling is per-username, not per-IP;
- audit writes are best effort, so a storage outage can leave a gap that is visible in
  metrics but not in the data.
- the console keeps the master key in page memory until the session UI ships; that is the
  next step, and the backend is ready for it.

## 4. API surface

- `POST /api/v1/auth/login` (public), `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`.
- `GET/POST /api/v1/admins`, `PATCH /api/v1/admins/{id}` (owner only).
- `GET /api/v1/admin-audit` (owner/auditor) with actor, action, target, and time filters.
- All existing management routes now resolve an admin principal instead of a master key.

## 5. References

- `src/llm_gateway/auth/passwords.py`, `auth/admin_auth.py`, `auth/admin_deps.py`
- `src/llm_gateway/services/admin_audit.py`, `services/bootstrap.py`
- `alembic/versions/0009_admin_identity.py`
- `tests/test_admin_auth.py`, `tests/test_postgres_repositories.py`
