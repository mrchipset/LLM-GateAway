# Cost accounting, plans, and budgets

Status: implements TODO G1.4. Scope: backend, admin API, enforcement. The console does not
edit prices or plans yet and does not chart cost.

## 1. Problem

`usage_records` stored tokens only, so operators could not answer "what did this tenant cost
this month", and there was no way to sell or cap a monthly allowance. The gateway also had no
notion of a prepaid plan: every tenant was effectively unmetered on price.

## 2. Decisions

### 2.1 Price list is versioned per model

`model_prices(model_id, input_per_million, cached_input_per_million, output_per_million,
currency, effective_from)` with a unique `(model_id, effective_from)`.

- Prices are per million tokens, the unit providers actually publish.
- A new price is an appended row, never an update. Historical cost therefore never has to be
  recomputed, and a price change cannot silently rewrite last month's bill.
- `cached_input_per_million` is optional and falls back to the input price. Providers rarely
  publish a cache-read price; requiring one would block adoption.
- The effective price is the newest row with `effective_from <= request time`. A future
  `effective_from` is allowed and becomes active on its own.

### 2.2 Store money on the usage row, not in a separate ledger

Each `usage_records` row gains `list_cost`, `billed_cost`, `covered_tokens`,
`billable_tokens`. The amounts are `NUMERIC(18, 6)` and are computed with `Decimal`, never
floats: `0.1 + 0.2` drift becomes a billing dispute after a million requests.

- `list_cost` is what the traffic would cost at list price. It is recorded even inside a plan,
  so gross margin stays visible.
- `billed_cost` is what the tenant owes: zero inside the plan, list price for the excess.
- Storing the result rather than the price reference keeps reporting independent of later
  price edits. The trade-off is that a mis-priced request cannot be retroactively repriced;
  correcting it means writing a manual adjustment, which is the same trade-off every billing
  system makes.

### 2.3 Plans are token allowances, two-segment priced

The product decision was a monthly **token** allowance with usage inside it free and usage
above it at list price.

- `tenants.plan_tokens` (nullable), `plan_allow_overage` (default false).
- Reset is the UTC calendar month, no rollover, no expiry bookkeeping. A plan row is a small
  amount of state because the period is derived from the clock.
- Inside the allowance, `covered_tokens` is capped by the allowance remaining and the excess
  becomes `billable_tokens`.
- Because prices differ by token category but the allowance is a single token count, the
  allowance is split across `(uncached prompt, cached, completion)` pro rata to the request's
  own mix, in whole tokens, with the remainder assigned deterministically. This avoids the
  cliff where the request crossing the boundary pays full price for every token.
- Billing counts `prompt + completion` as the token measure. Some providers report a
  `total_tokens` that includes extra buckets; that number is stored for reporting but not
  used to consume the allowance, so the ledger stays internally consistent.

`plan_allow_overage` resolves the apparent contradiction between "hard block" and "overage at
list price":

- `false` (default): once the allowance is exhausted, `POST /v1/chat/completions` returns
  429 `plan_allowance_exhausted`.
- `true`: traffic continues, the excess is billed, and the monthly cost budget is the hard cap.

A request that starts just before exhaustion can overshoot the allowance; the overshoot is
billed. Preventing that needs pre-call token estimation and atomic reservation (see 2.6).

### 2.4 Budget is a currency cap on billed cost

`tenants.monthly_cost_budget NUMERIC(18, 6)` caps `billed_cost` per UTC month and returns 429
`budget_exceeded`. It is deliberately separate from the plan:

- A plan bounds what is free; a budget bounds what is owed.
- Companies that want "no plan, but do not spend more than X" set only the budget.
- Companies that want "1M tokens free, then stop" set only the plan with overage disabled.

The budget counts `billed_cost`, not `list_cost`, so plan-covered traffic does not consume the
budget twice.

### 2.5 Unpriced traffic fails closed only when it matters

If a tenant has a plan or a budget, its models must have a price; otherwise inference returns
503 `model_price_missing` and logs/metrics the event. A budget that cannot be priced is not a
budget.

Tenants with neither a plan nor a budget keep working with unpriced models: cost fields stay
`null`, and no behavior changes for existing deployments. This preserves backward
compatibility while making the failure mode explicit for anyone who opts into billing.

### 2.6 Concurrency: no reservation, by decision

Enforcement reads the period total before the request and settles costs after it. Concurrent
in-flight requests can therefore overshoot by at most their own usage.

This is an explicit product decision, not a missing feature. Pre-call reservation would need a
token estimate (this gateway has no tokenizer) or a conditional counter row plus reserve/settle
bookkeeping in the hot path, and the accepted bound is already small: a tenant can overshoot by
the usage of the requests that were in flight when the limit was crossed, not by an unbounded
amount. The existing token quota has the same behavior.

Revisit only if a tenant can demonstrate a materially larger overshoot than one request window,
or if a customer contract requires a hard not-to-exceed guarantee. In that case the cheap path is
a conditional monthly counter row, not Redis.

### 2.7 Reconciliation with existing quotas

`monthly_token_quota` (hard token cap) and `plan_tokens` (included allowance) can coexist.
Order of checks: quota, rate limit, plan allowance, budget. The quota is checked first because
it is an absolute cap; the plan check only fires when overage is disabled.

### 2.8 Kill switch

`GATEWAY_BILLING_ENABLED=false` skips plan/budget authorization entirely for inference
requests: no month aggregate, no price lookup, no 429. Usage rows still record token counts,
but `covered_tokens`, `billable_tokens`, `list_cost`, and `billed_cost` stay unset, and
`GET /tenants/{id}/billing` reports `enabled: false` so the zeros are not mistaken for real
spend. The process logs `billing_disabled` at startup.

This exists because the month aggregate is the measured hot-path bottleneck (see
`notes/load-baseline.md`). It is an escape hatch for environments where enforcement is not yet
required, not a production mode:

- costs are not settled while it is off, so budget enforcement must not be re-enabled mid-period
  without backfilling the unset rows from versioned prices;
- turning it off does not delete plan configuration; it only bypasses the check.

## 3. Consequences

Positive:

- cost per request, per tenant, per model, per key, per day is queryable;
- price changes are auditable through rows, not memory;
- plan and budget are one PATCH away, with no schema change per tenant type;
- unpriced billing is impossible to enable silently.

Negative:

- one extra price lookup and month aggregation per billed request;
- pro-rata splitting is an approximation of "which tokens were free"; it is deterministic and
  documented, but it is not what an invoice line-by-line reconciliation would produce;
- no invoicing, no multi-currency, no per-key budgets, no credit top-ups or rollover;
- concurrent requests can overshoot a plan or budget by their own usage (no reservation, by
  decision; see 2.6).

## 4. API surface

- `POST /api/v1/models/{id}/prices`, `GET /api/v1/models/{id}/prices`.
- `PATCH /api/v1/tenants/{id}` accepts `plan_tokens`, `plan_allow_overage`,
  `monthly_cost_budget`; explicit `null` clears a limit.
- `GET /api/v1/tenants/{id}/billing` returns the current period totals.
- Usage summary / by-key / series responses expose `covered_tokens`, `billable_tokens`,
  `list_cost`, `billed_cost`.

## 5. References

- `src/llm_gateway/services/billing.py` (split, pricing, authorization)
- `alembic/versions/0008_billing.py`
- `tests/test_billing.py`, `tests/test_postgres_repositories.py`
- Related: `notes/model-access.md`, TODO G1.4, G1.3 (hot path), G1.7 (load baseline)
