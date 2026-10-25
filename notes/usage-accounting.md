# Token usage accounting

Status: implemented in `storage/`, `services/usage.py`, `api/inference.py`,
`api/admin/usage.py`, and migration `0003`.

## Problem and constraints

Operators need to know how many input, output, and cache-hit tokens each tenant,
key, and model consumes. Providers report usage differently: OpenAI returns
`usage` on every non-stream response and an optional usage-only stream chunk;
DeepSeek attaches usage to the last content chunk and does not emit a separate
chunk. Recording must not change the client contract, must not fail a successful
inference request, and must keep memory-backend tests dependency-free.

## Assumptions

- Usage is recorded for observability and as the baseline for tenant quotas. Cost
  conversion and billing are still out of scope; quota enforcement itself is
  described in `notes/quotas-and-rate-limits.md`.
- Only requests that produce usage are recorded. Transport failures and streams
  that never report usage have no token counts to store.
- `cached_tokens` is a subset of `prompt_tokens`, never an additional bucket.
  Adding them together double-counts tokens.
- The reported `total_tokens` is stored as-is rather than recomputed. Providers
  may include cached or reasoning tokens differently; silently rewriting the
  number would hide upstream inconsistencies.
- Aggregates are small enough for synchronous `sum`/`count` queries. No
  materialized rollups or ClickHouse.

## Options considered

**Record only when the client requests `stream_options.include_usage`.** This
keeps the stream byte-for-byte identical but produces no numbers for the default
client. Rejected for the stated goal.

**Always inject `include_usage` and forward everything.** Accurate numbers, but
clients that did not ask for usage suddenly receive an extra chunk. Rejected;
the gateway suppresses usage-only chunks unless the client asked, while keeping
DeepSeek's usage-on-content-chunk behavior untouched.

**Record synchronously in the response path vs a background queue.** A queue
(Redis/worker) adds infrastructure this project explicitly does not have yet.
Synchronous writes are bounded by a 2s timeout and shielded during stream
cleanup; failures are logged and never surfaced to the client. Revisit if the
write path becomes a bottleneck.

**Store a models foreign key vs a denormalized `model_id`.** Models can be
deleted while history must survive, so usage stores `model_id` + `provider` as
text (no FK). Tenants and API keys use `RESTRICT` FKs because they are never
deleted today and history must not silently disappear.

**Two queries (totals + grouped) vs one grouped read.** Totals are derived from
the grouped result so `requests` always equals the sum of the breakdown and both
come from one transaction.

## Chosen approach

- `usage_records(id, request_id, tenant_id, api_key_id, model_id, provider,
  prompt_tokens, completion_tokens, total_tokens, cached_tokens, created_at)`,
  with `(tenant_id, created_at)`, `(model_id, created_at)`, `api_key_id`,
  `created_at`, and `request_id` indexes.
- `extract_token_counts` normalizes OpenAI
  `prompt_tokens_details.cached_tokens` first, then DeepSeek
  `prompt_cache_hit_tokens`; anything else (bool, float, negative, malformed) is
  ignored and becomes 0.
- Non-stream: the service returns `ChatCompletionResult` (response + resolved
  model) so the endpoint records with the correct model/provider without a
  second registry read.
- Stream: `ChatService.open_stream` injects `include_usage=true`, keeps the
  client's other `stream_options`, prefetches until a content chunk, and
  suppresses usage-only chunks unless the client requested usage. `ChatStream`
  keeps the last reported usage; the SSE `finally` shield-closes the upstream
  stream and records usage within the same shielded block, bounded by a 2s
  timeout.
- Recording failures log `usage_record_failed` (with request id, model id, error
  type only) and `usage_unavailable` when no usage arrived; neither changes the
  HTTP response.
- `GET /api/v1/usage/summary` filters by `tenant_id`, `model_id`, and a
  half-open `[since, until)` window, and returns totals plus `by_model`.
  `by_model` groups by `(model_id, provider)`: if a public model id is later
  re-registered under another provider, it appears as two rows rather than being
  merged under an ambiguous provider.
- `request_id` is limited to 64 characters in the request-id middleware so it
  always fits the column; longer client values are replaced with a generated id.

## Trade-offs and risks

- `usage_records` grows with every successful inference request. There is no
  retention, partitioning, or archival job yet; production deployments must add
  one before the table becomes large.
- A successful upstream request can be unbilled locally if the process crashes
  between the response and the usage write, if the client disconnects during
  shutdown, or if the write times out. This is best-effort accounting by design.
- Recorded values are provider-reported. A provider that omits usage yields no
  row; a provider that reports inconsistent totals is stored verbatim.
- Cached-token semantics differ (OpenAI cache reads vs DeepSeek cache hits);
  the normalized column means "prompt tokens served from a provider cache".
- The summary is offset/aggregate only: no time-bucketed series, no per-key
  endpoint, and no cost. Those are follow-ups, not silent gaps.
- The admin UI does not display usage yet.

## References

- `src/llm_gateway/services/usage.py`, `services/chat.py`
- `src/llm_gateway/api/inference.py`, `api/admin/usage.py`
- `src/llm_gateway/storage/{repositories,tables,sql,memory}.py`
- `alembic/versions/0003_usage_records.py`
- OpenAI `usage.prompt_tokens_details.cached_tokens`; DeepSeek
  `usage.prompt_cache_hit_tokens`
- `notes/tenants.md`, `notes/inference-and-providers.md`
