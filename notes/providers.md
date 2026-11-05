# Provider breadth: Azure OpenAI and Anthropic

## Problem

Every provider went through one OpenAI-compatible adapter. DeepSeek fits that shape; Azure and
Anthropic do not:

- Azure keeps the OpenAI payload but routes by deployment name in the path, uses the `api-key`
  header, and requires `api-version`.
- Anthropic Messages has a different request body (top-level `system`, mandatory `max_tokens`,
  `tool_use`/`tool_result` blocks), a different response shape, and a different SSE vocabulary.

Provider differences must stay inside the adapter; routing, billing, guards, and audit see only
the internal OpenAI-shaped contract.

## Decisions

### Azure is a subclass, not a translation layer

`AzureOpenAIProvider` extends `OpenAIProvider` and changes exactly two things: the endpoint
(`/openai/deployments/<name>/chat/completions?api-version=...`) and the auth header (`api-key`).
Everything else — retry, SSE parsing, usage, TTFT — is identical, so sharing the implementation is
correct rather than convenient.

The deployment name comes from the model's `upstream_model`, which is why Azure is always built per
deployment by `ProviderPool` instead of once from settings. A trailing `/openai` in the configured
base URL is stripped so both `https://resource.openai.azure.com` and `.../openai` work.

### Anthropic is a full translation adapter

`AnthropicProvider` implements the same `ChatProvider` protocol but builds Messages payloads
explicitly (no blind forwarding of OpenAI fields) and translates both directions:

| OpenAI | Anthropic |
|---|---|
| `system` / `developer` messages | top-level `system` string |
| `max_tokens` (optional) | `max_tokens` (required; falls back to `ANTHROPIC_DEFAULT_MAX_TOKENS`) |
| `stop` | `stop_sequences` |
| `tools[].function` | `{name, description, input_schema}` |
| `tool_choice` | `{type: auto|any|tool}`; `none` omits tools |
| assistant `tool_calls` | `tool_use` content blocks |
| `tool` message | `tool_result` block, consecutive results grouped into one user turn |
| response `text`/`tool_use` blocks | `message.content` / `tool_calls` |
| `input_tokens`/`output_tokens` | prompt/completion/total tokens |
| `cache_read_input_tokens` | `prompt_tokens_details.cached_tokens` |

Streaming maps `content_block_delta` (`text_delta`, `input_json_delta`) to OpenAI deltas, uses
`message_stop` as the completion sentinel (there is no `[DONE]`), and emits a final usage chunk
even when the client did not ask for one — the gateway always asks upstream for usage so billing
is complete.

Non-text blocks (`thinking`) and non-text OpenAI content parts raise a typed error instead of being
dropped: silently discarding content would produce a response that no longer matches the request.

### Capabilities are metadata with request-time enforcement

`models` now carries `context_window`, `max_output_tokens`, `supports_tools`, and
`supports_streaming`. `ChatService` checks the last three (and `max_tokens <= max_output_tokens`)
after resolving the model and before any upstream call, returning 400 `request_limit_exceeded`
with a `param`. The context window is recorded for capacity planning only: there is no tokenizer in
the gateway, and prompt limits stay character-based.

Defaults are permissive (`supports_* = true`, null limits) so existing models keep working after
the migration.

## Trade-offs and gaps

- Bedrock and Vertex are not implemented. They need AWS SigV4 signing / Google OAuth and a
  credential model beyond a single env-var key; that is a separate stage with its own tests.
- Anthropic prompt caching is read-only in the mapping: `cache_creation_input_tokens` is not
  priced or exposed, and cache-control breakpoints requested by clients are not forwarded.
- Anthropic `thinking`/reasoning blocks are rejected rather than mapped; a client that needs them
  needs a new internal field, not an adapter hack.
- Azure's `api-version` is global; per-deployment versions would need another column.
- Capabilities are fixed at creation; the PATCH endpoint does not accept them, so changing them
  requires delete and recreate.
