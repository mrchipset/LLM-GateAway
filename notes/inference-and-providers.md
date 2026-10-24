# Inference path: providers, auth, and streaming

Status: implemented in `src/llm_gateway/{providers,auth,services,api/inference.py}`.

## Problem and constraints

Serve OpenAI-compatible `POST /v1/chat/completions` (stream and non-stream) and
`GET /v1/models` for at least one real provider and one fake provider, with API
key auth, bounded retries, explicit timeouts, and predictable behavior for
first-chunk failures and client disconnects. Provider-specific details must stay
inside the adapter; routing and the request pipeline must not branch on them.

## Assumptions

- One registry entry maps one public model name to exactly one upstream model
  for the MVP. Multi-deployment routing, weights, and fallback are explicitly
  out of scope.
- Provider credentials live in environment configuration, not in the database.
  Model records therefore store only `provider` + `upstream_model`, avoiding
  secret encryption in the MVP.
- Clients tolerate a gateway error frame inside an SSE stream because the HTTP
  status is already committed at that point.
- The public model name is the stable contract; `upstream_model` may change
  without breaking clients.

## Options considered

**Model routing by name convention (`openai/gpt-4o`) vs registry lookup.** A
registry lookup keeps the public model name free of provider syntax and makes
the mapping explicit and auditable. It also gives the admin API something
concrete to manage.

**Passing upstream JSON around as `dict` vs typed models.** Typed Pydantic
models at the provider boundary catch malformed upstream payloads early and give
the SSE parser and the API layer one shared shape. Unknown request fields are
still forwarded via `extra="allow"` so OpenAI client compatibility does not
regress.

**Retrying the whole request vs retrying only before the first byte.** For
non-stream requests retries are straightforward. For streams, a retry after
bytes have been forwarded would duplicate content, so retries are limited to
connection setup and the HTTP status check. Anything after the first byte
becomes a terminal SSE error frame.

**Parsing SSE with `aiter_lines` vs an incremental UTF-8 byte buffer.** The
buffer approach handles an event split across arbitrary TCP chunks and a
multi-byte character split across chunks; `aiter_lines` hides boundary bugs
instead of covering them with tests.

**Buffering the first stream chunk vs streaming immediately.** The service
awaits exactly one chunk before returning the HTTP response. Upstream failures
therefore become normal JSON errors with a real status code instead of a
half-open 200 stream.

**Storing the API key vs storing its hash.** Only a SHA-256 hash and a short
display prefix are persisted. Unknown, revoked, and expired keys share one error
message so the gateway does not disclose key state.

## Chosen approach

- `ProviderName` -> `ChatProvider` is resolved by a `ProviderRegistry` built at
  startup. A missing provider is a 503 `provider_not_configured`, not a silent
  fallback.
- `OpenAIProvider` owns its `httpx.AsyncClient` (explicit `httpx.Timeout`, and a
  bounded retry policy with full-jitter backoff). It maps transport failures to
  timeout/connection errors and non-2xx responses to `ProviderUpstreamError`.
  Provider error messages are truncated to 300 characters.
- `FakeProvider` is deterministic, clock-injected, and used by tests and local
  demos. Production configuration rejects it.
- `ChatService` owns model resolution and error mapping. Upstream 401/403 becomes
  502 `upstream_auth_failed` (never echoing the upstream credential message),
  429 stays 429, other 4xx becomes 400 `upstream_rejected`, 5xx/timeouts become
  502/504. All upstream failures use the standard `server_error` type.
- `ChatStream` prefetches the first chunk, rewrites every chunk's `model` to the
  public model name, and closes the upstream async generator idempotently.
- The SSE generator always closes the stream in `finally`, so disconnects and
  cancellations release the upstream connection. Mid-stream failures emit one
  `data: {"error": ...}` frame followed by `data: [DONE]`.
- Inference routes use `require_api_key`; the master key is rejected there with
  `master_key_not_allowed`. Request authentication updates `last_used_at`
  best-effort and logs a warning if the write fails.
- `GET /v1/models` returns enabled models only, capped at 1000 entries.

## Trade-offs and risks

- `extra="allow"` on the request model means unknown provider parameters are
  forwarded without validation. This is deliberate for compatibility; a strict
  mode can be added later.
- No tokenizer or cost accounting yet; usage is whatever the provider reports
  (and the fake provider's word count).
- Mid-stream errors are delivered inside a 200 response. Clients must inspect
  the error frame; this matches common SSE proxy behavior but is not caught by
  HTTP status handling.
- `last_used_at` adds one write per inference request. At scale this should be
  sampled or batched; the MVP favors observability.
- Retry policies are not configurable per provider beyond `GATEWAY_MAX_RETRIES`.
- Rate limiting, request logs, and spend accounting are not part of this phase.

## References

- `src/llm_gateway/providers/openai.py` (SSE parser, retry loop)
- `src/llm_gateway/services/chat.py` (model resolution, error mapping, stream)
- `src/llm_gateway/api/inference.py` (SSE framing, first-chunk error contract)
- `src/llm_gateway/auth/keys.py`, `auth/dependencies.py`
- `design.md` sections 2.1, 2.2, 4.8
- `architecture.md` section 6.3 (streaming semantics worth preserving)
