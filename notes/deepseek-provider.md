# DeepSeek provider: parameterizing the OpenAI-compatible adapter

Status: implemented in `providers/{base,openai,factory}.py` and `config.py`.

## Problem and constraints

Operators want DeepSeek alongside OpenAI. DeepSeek exposes an OpenAI-compatible
Chat Completions API, so the question is not "can we add a provider" but "how do
we add it without forking the retry, streaming, and error-mapping logic that was
expensive to get right". `AGENTS.md` forbids copy-paste and speculative
abstractions.

## Confirmed facts (official docs, 2026-10)

- Endpoint: `POST https://api.deepseek.com/chat/completions`; the OpenAI-style
  base URL is `https://api.deepseek.com` (no `/v1` required). The older `/v1`
  alias is historical and not documented as current.
- Auth: `Authorization: Bearer <key>`.
- Current model ids: `deepseek-flash`, `deepseek-v4-pro`. The older
  `deepseek-chat` / `deepseek-reasoner` ids are retired.
- Streaming is SSE with a terminal `data: [DONE]`. With
  `stream_options.include_usage=true`, usage is attached to the last content
  chunk; DeepSeek does not emit a separate `choices: []` usage chunk.
- Reasoning text is `reasoning_content` on `choices[].message` and
  `choices[].delta`; `content` carries the final answer.
- DeepSeek returns 400 for `stream_options` without `stream: true`, and for tool
  loops whose historical assistant messages omit `reasoning_content`.
- Error bodies are not documented field-by-field; only status codes (400, 401,
  402, 422, 429, 500, 503) are listed. Never rely on `Retry-After` or a
  provider-specific `code`.

## Options considered

**A dedicated `DeepSeekProvider` subclass.** It would add a type with no
behavior: same headers, same payload, same SSE framing, same error shapes.

**A copied adapter.** Duplication means every retry or stream fix (the buffered
`post` bug, truncation detection, disconnect cleanup) has to be made twice, and
the tests would diverge. Rejected.

**Parameterize the existing adapter with `name` + `base_url` (chosen).** The
wire protocol is the same; the only differences are the endpoint, the credential,
and the model ids stored in the registry. One adapter keeps one tested code path.

## Chosen approach

- `OpenAIProvider` gains `name: ProviderName = ProviderName.OPENAI` and keeps the
  class attribute as a default. All other behavior is unchanged.
- `ProviderName.DEEPSEEK` exists so the registry, model records, and
  `owned_by` values are explicit.
- `Settings` gains `deepseek_api_key` (disabled when unset) and
  `deepseek_base_url` (default `https://api.deepseek.com`).
- The factory builds both providers through one private helper so timeout and
  retry policy cannot drift.
- Model ids stay in the registry, never hardcoded in the adapter, because
  DeepSeek renames models over time (as the retired chat/reasoner ids show).
- `ChatMessage`/`ChatDelta` keep `extra="allow"`, so `reasoning_content` flows
  through responses and stream deltas untouched; regression tests lock both
  directions.

## Extensibility model

1. **OpenAI-compatible provider** (DeepSeek, OpenRouter, Groq, vLLM): add an enum
   member, two settings fields, one factory registration, docs. No changes to
   the API, service, auth, or storage layers.
2. **Different protocol** (Anthropic Messages, Bedrock, Vertex): implement
   `ChatProvider.complete` and `.stream`, translate requests/responses into the
   typed schemas, and register it. The service, endpoints, errors, keys, and UI
   stay unchanged.
3. **Multi-deployment routing, fallback, cooldown, weights**: not a provider
   concern. It requires extending `ModelConfig`/the registry and the resolution
   step in `ChatService`; do not fake it inside an adapter.

## Trade-offs and risks

- No per-provider parameter whitelist. DeepSeek silently ignores some
  undocumented fields and rejects others (for example `stream_options` without
  `stream`), which surfaces as `upstream_rejected` with the upstream message.
- Reasoning-model latency can exceed the default 60s read timeout; operators
  must raise `GATEWAY_REQUEST_TIMEOUT_SECONDS` for long thinking runs.
- `reasoning_content` round-tripping for tool calls depends on the client sending
  it back in historical assistant messages; the gateway only preserves fields it
  receives.
- Provider names are not validated against the adapter class; passing `FAKE` to
  `OpenAIProvider` would mislabel it. The factory is the only construction site.
- No live DeepSeek call runs in CI; the adapter is verified with respx against
  recorded request/response shapes. A real smoke test requires an API key.

## References

- `https://api-docs.deepseek.com/api/create-chat-completion`
- `https://api-docs.deepseek.com/quick_start/error_codes`
- `https://api-docs.deepseek.com/guides/thinking_mode`
- `src/llm_gateway/providers/openai.py`, `factory.py`, `base.py`
- `tests/providers/test_factory.py`, `tests/providers/test_openai.py`
