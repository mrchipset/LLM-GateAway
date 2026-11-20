# Downstream SSE keepalive during silent prefill

## Problem

A long prompt can spend minutes in upstream prefill before the first content (or even
reasoning) token. Upstreams such as ninfer send SSE comments (`: keep-alive`) during this
window, but the OpenAI adapter drops every non-`data:` line (`providers/openai.py:63-71`),
so the downstream client sees no bytes at all. Clients that time out on idle reads then
abort a stream the gateway is still holding open.

Raising the gateway's timeouts does not help: the abort comes from the client, and the
gateway logs it as `client_disconnected=true` with no upstream error.

## Decision

Add `GATEWAY_STREAM_KEEPALIVE_SECONDS` (default `0`, disabled). When positive, the gateway
emits `: keepalive\n\n` while it waits for the next chunk from the upstream and no chunk
arrives within the interval.

Implementation (`api/inference.py`):

- A pump task owns `stream.chunks()` and pushes chunks, exceptions, and a done sentinel
  into a bounded queue.
- The response loop waits on the queue with `asyncio.wait_for`. A timeout yields a keepalive
  frame and keeps waiting; it never cancels the upstream read (cancelling `anext` would
  close the stream).
- Client disconnects still cancel the pump, which closes the upstream through the existing
  `ChatStream.chunks()` finally block; the response finally block also calls `stream.aclose()`
  (idempotent).

## Limitations

- The first chunk is still prefetched before the response starts (`services/routing.py:300`),
  so a request where the upstream sends no chunk at all gets no keepalive. The common case —
  an initial role chunk followed by a silent prefill — is covered.
- SSE comments are ignored by many SDKs, including the OpenAI Node SDK used by
  deepseek-harness. They reset socket-level idle timers, not watchdogs built on parsed
  chunks. A client with a total request deadline will still abort.
- This is a liveness mechanism, not a substitute for fixing an upstream that produces no
  tokens for minutes.

## Tests

`tests/test_stream_keepalive.py`: a slow upstream produces at least one `: keepalive` frame
before content when enabled, and none when disabled; content and `[DONE]` are unchanged.
