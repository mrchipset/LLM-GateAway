# Request audit: session capture and turn diffs

## Problem and constraints

The gateway only recorded usage metadata. Operators need to reconstruct what a chat
request actually sent and how consecutive turns differ, without turning the gateway into
a semantic analytics product.

Constraints that shaped the design:

- OpenAI chat is stateless; clients may resend the full message list or only the newest
  message. Session identity is therefore best-effort unless the client cooperates.
- Audit content can contain PII, business data, or pasted secrets. It must be off by
  default, master-key-only, never written to stdout logs, browser storage, cookies, or
  URLs.
- Audit must never change the inference response or status. Writes are best-effort with
  a bounded timeout and observable failures.
- Storage and migrations are PostgreSQL + Alembic and additive only.
- The inference contract stays OpenAI-compatible; an optional session header is the only
  addition.

## Decisions

### Dual opt-in and header handling

`GATEWAY_AUDIT_ENABLED` (global kill switch) and tenant `audit_enabled` must both be true.
When either is false the code returns before reading the session header, reading the
tenant flag's consequences, or touching the audit repository. An invalid
`x-llm-gateway-session-id` returns 400 only when audit is active, so disabling audit can
never break a client that sends a malformed header.

The header is 1..64 chars of `[A-Za-z0-9._:-]`, scoped to the tenant, and used only for
grouping. It deliberately spans API keys and models so a client can keep one conversation
across key rotation; the fallback path is key-scoped to avoid merging unrelated
applications of the same tenant.

### Session resolution and turn numbering

Explicit header wins and skips prefix queries. Without a header, the service loads only
hash-level rows (`recent_prefix_requests`: request id, session id, turn index, message
hashes, timestamp) for the same tenant + API key in the last 24 hours (max 200), picks the
longest common prefix that extends past the first user message, and loads one parent
snapshot. A shared system prompt alone never merges conversations. Ties go to the newest
candidate.

`turn_index = parent.turn_index + 1`, as specified in TODO. Multiple children of the same
parent (branches, retries, concurrent requests) may therefore share a turn index; reads use
a total order `(turn_index, created_at, request_id)` instead of a uniqueness constraint.
`ensure_session` uses an upsert on the partial unique index `(tenant_id,
external_session_id)` so two concurrent first requests converge on one session instead of
one losing a turn. A pre-created session with `request_count = 0` is hidden from
`list_sessions`; its metadata is reconciled by the first successful turn. This avoids
ghost sessions whose root request id points at nothing.

Rejected: a monotonic session-wide turn counter and a unique `(session_id, turn_index)`
index. Both contradict the branch semantics in TODO and would make concurrent branches
fail loudly for legitimate traffic.

### Deterministic diff

Messages are canonicalized over role/content/name/tool_calls/tool_call_id, sorted-key
compact JSON, SHA-256 per message. The diff stores indexes, roles, hashes, ≤160-char
previews, parameter from/to (whitelist), usage delta, and response hashes/counts. Full
content lives only in the request snapshot; the diff table never duplicates it.

Large parameter values (for example a tool schema) are replaced with
`{from_hash, to_hash, truncated: true}` at a quarter of the content budget. Without this,
the always-returned diff would bypass `audit_max_content_bytes` and leak the very payloads
that `include_content=false` is supposed to hide.

### Capture and failure isolation

Non-streaming calls audit after the provider response, before returning. Streaming
accumulates only choice index 0, merges tool calls by index, and records in the shielded
`finally` so client disconnects still persist partial content. Status mapping:

- `completed`, `upstream_error`, `client_error`, `client_disconnected`, `error`.
- Provider errors are already mapped to `ApiError` by the chat service, so classification
  uses `code.value.startswith("upstream_")`, not the exception class.

Writes use `asyncio.timeout(audit_write_timeout_seconds)` and swallow all errors except
the client-facing header validation. Logs contain only request/tenant/session/model/
provider/status and the exception type.

### Payload budget and privacy split

The capture budget covers messages, response, request params and response tool calls
(UTF-8 bytes, UTF-8-safe truncation). Hashes and diffs are computed on the original
content before truncation so matching stays stable; `truncated=true` is stored whenever
anything was shortened.

The read API measures the actual serialized response in both content modes. This matters
because previews and hashes still consume bytes. `include_content=false` returns metadata
plus diff previews (explicitly allowed by TODO and useful) but no full snapshots, and all
parameter changes are hashed. The UI copy says "preview excerpts", not "no content". A
session over budget returns 413 and the UI falls back to per-request detail.

Rejected: stripping previews entirely from the default view. It would make the default
timeline useless and contradict TODO's "short preview" allowance while providing no real
privacy gain, because previews are bounded, master-key-only, and parameter plaintext is
already hashed.

### Performance

The default timeline uses `list_session_request_summaries`, a column projection that never
reads JSONB bodies (SQL computes `jsonb_array_length(request_messages)`). Diffs are fetched
in one batched query. Content mode loads full rows only when requested.

## Trade-offs and open gaps

- Prefix matching can still over-merge similar conversations if they share the same key,
  system prompt and first user message beyond the date window boundary.
- No terminal-user identity; tenant + key is the actor.
- Retention cleanup, export/delete APIs, partitioning, metrics, and audit-access logging
  are deferred (P1e). Until they exist, operators must manage data volume manually.
- No PII redaction beyond not logging headers/keys and the size budget.
- Branches are presented linearly with turn indices and metadata; no tree editor.
