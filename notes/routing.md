# Multi-deployment routing and failover

Status: implements TODO G1.1. Scope: backend, admin API. The console does not edit
deployments yet.

## 1. Problem

One public model mapped to exactly one upstream. A provider outage (5xx, 429, a bad
credential) reached the client directly, and there was no way to spread traffic across two
accounts or two providers without registering a second public model and asking clients to
switch.

## 2. Decisions

### 2.1 Deployments are additive, not a replacement

`models` stays the public registry. `model_deployments` adds zero or more routes per model.
Zero rows means the existing provider/upstream pair is the single implicit deployment, so
upgrading changes nothing and no data migration is required.

Each row carries `name`, `provider`, `upstream_model`, `weight` (1–100), `enabled`, an
optional `credential_env`, and an optional `base_url`. `(model_id, name)` is unique.

### 2.2 Credentials are environment variable names

`credential_env` stores the *name* of an environment variable, never the secret. The provider
pool resolves it at request time and caches one HTTP client per `(provider, env var,
base_url)`.

Why: encrypting secrets at rest requires a KMS and a rotation story, and the gateway already
expects its provider keys from the environment. Naming an env var keeps the same trust model
while enabling several accounts per provider (`OPENAI_PRIMARY_KEY`, `OPENAI_BACKUP_KEY`).

Deployments without overrides reuse the provider built from settings, which is what makes the
legacy path work unchanged.

A missing env var is a deployment-level configuration error: it is recorded as a failed
attempt and the router moves on. If every candidate is misconfigured the client gets 503
`deployment_credential_missing` or `provider_not_configured`, never a 500.

### 2.3 Ordering: weighted random without replacement

Candidates are selected by weighted random sampling without replacement. The first pick is
the primary, the rest are fallbacks, bounded by `GATEWAY_ROUTE_MAX_ATTEMPTS`.

With equal weights every deployment is equally likely to be first; with `3:1` the primary is
three times more likely. This is enough for gradual rollout and A/B cost experiments without
introducing the routing zoo the design note warns about (latency-based, cost-based, tag-based).

### 2.4 What fails over

| Condition | Fail over? | Cooldown? |
|---|---|---|
| timeout, connection error | yes | yes |
| upstream 429, 5xx | yes | yes |
| upstream 401/403 (bad credential) | yes | yes |
| invalid/unparseable upstream payload, empty stream | yes | yes |
| upstream 400/422 (request is wrong) | no | no |
| missing credential env / unconfigured provider | yes | no |

The distinction matters: a malformed request should not burn every deployment, and a bad
region-wide credential should not be retried forever.

### 2.5 Cooldown is process-local, on purpose

`DeploymentHealth` counts consecutive failovers and puts a deployment into cooldown after
`GATEWAY_ROUTE_FAILURE_THRESHOLD` (default 3) for `GATEWAY_ROUTE_COOLDOWN_SECONDS`
(default 30). State lives in memory.

Trade-off: with several workers, each process learns independently, so a failing deployment
may still receive traffic from a worker that has not seen failures. Shared health needs Redis,
which is the same dependency as the rate-limit work (TODO G1.2); coupling them avoids two
migrations and two counters.

A cooldown never removes the last candidate: if every deployment is cooling down, the router
still tries, preferring the one whose cooldown expires first.

### 2.6 Provider retries stay inside the deployment

The provider adapter already retries transient errors before the first byte. The router adds
deployment-level failover **after** that. This keeps the single-deployment behavior identical
and makes failover a configuration choice: set `GATEWAY_MAX_RETRIES=0` to get one attempt per
deployment and the fastest switchover.

The cost is that a request may spend `retries × attempts` time before failing. Operators who
care about tail latency during an incident should lower the provider retries.

### 2.7 Observability

- `gateway_route_attempts{provider,model,deployment,status}` — every attempt, including the
  ones that fail.
- `gateway_route_fallbacks{model}` — requests that succeeded on a non-primary deployment.
- `gateway_deployment_cooldowns{deployment}` — cooldown entries.
- A trace span `route.attempt` per attempt with `llm.deployment`, `llm.provider`,
  `llm.upstream_model`, `llm.route_attempt`, `llm.route_status`.
- Response headers `x-llm-gateway-deployment` and, when applicable,
  `x-llm-gateway-fallback: true`.

## 3. Consequences

Positive:

- provider outages degrade instead of failing;
- multiple accounts per provider without duplicating public model names;
- no secrets in the database;
- existing models keep working with no migration.

Negative:

- cooldown is per process until Redis lands;
- weight is static; there is no dynamic latency or cost routing;
- failure attribution stops at the provider in `usage_records`; per-deployment usage is not
  stored yet, so cost per deployment is only visible through the `deployment` metric label;
- failover can multiply the time spent before returning an error when provider retries are
  enabled.

## 4. References

- `src/llm_gateway/services/routing.py`, `providers/pool.py`
- `alembic/versions/0010_model_deployments.py`
- `tests/test_routing.py`, `tests/test_postgres_repositories.py`
- Related: TODO G1.2 (shared health), G1.7 (load baseline)
