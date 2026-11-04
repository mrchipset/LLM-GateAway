# Runtime parameters: pool, statement timeout, drain, idle streams

## Problem

The process had four hard-coded lifecycle assumptions that break under real deployment:

- pool size and overflow were fixed at `5 + 5`, which the load baseline showed is the first
  limit to hit under billing load;
- no statement timeout existed, so one bad aggregate could hold a connection indefinitely;
- shutdown had no notion of in-flight work — an active SSE stream was a connection task with
  no accounting;
- a stalled upstream produced a stream that hung until the client gave up.

## Decisions

### Pool is configuration, with bounds

`GATEWAY_DATABASE_POOL_SIZE` (1-100), `GATEWAY_DATABASE_MAX_OVERFLOW` (0-100), and
`GATEWAY_DATABASE_POOL_TIMEOUT_SECONDS` are settings validated by pydantic. The pool timeout is
no longer borrowed from the connect timeout: waiting for a slot and connecting are different
failure modes, and conflating them made the wait as long as the dial.

The ceiling exists because the real limit is PostgreSQL `max_connections`, divided by workers
and replicas. A single process with 100 connections is already anti-social; the validation stops
a typo from exhausting the server.

Rejected: auto-sizing from CPU count. It hides the multiplication by replicas, which is the
part that actually breaks.

### Statement timeout is server-side

`GATEWAY_DATABASE_STATEMENT_TIMEOUT_MS` (default 30000, `0` disables) is passed through asyncpg
`server_settings` rather than a client-side wrapper. PostgreSQL then cancels the query, releases
the lock, and returns a normal error; a client-side timeout leaves the backend running and the
connection unusable.

Default 30 s is deliberately generous for an OLTP gateway but short enough that a runaway month
aggregate fails instead of pinning a connection. The baseline showed the worst measured query
taking seconds, so this does not change normal traffic.

### Drain is tracked at the ASGI boundary

`InFlightTracker` is a counter plus an `asyncio.Event`. A pure ASGI middleware increments before
the app runs and decrements in `finally`; pure ASGI matters because `BaseHTTPMiddleware` returns
before a streaming body finishes, which would undercount exactly the requests that need draining.

On shutdown the lifespan waits for idle for up to `GATEWAY_SHUTDOWN_GRACE_SECONDS`. Uvicorn also
gets the same value via `--timeout-graceful-shutdown`, and Compose allows 45 s before SIGKILL, so
the order is: stop accepting, drain, uvicorn cancels at the ceiling, our wait observes whatever
is left, logs `shutdown_grace_exceeded`, counts `gateway_forced_shutdowns`, and releases the
pool.

The counter is defense in depth, not the primary mechanism: in current uvicorn the lifespan
shutdown runs after connection tasks are waited for, so a non-zero count means uvicorn had to
cancel. That is exactly the case an operator needs to see.

Rejected: application-level task registry per request. The ASGI boundary already knows when a
response body is complete, including a stream, and needs no per-request bookkeeping.

### Idle timeout applies to the gap, not the stream

The OpenAI adapter wraps each `__anext__()` on `response.aiter_bytes()` in
`asyncio.timeout(GATEWAY_STREAM_IDLE_TIMEOUT_SECONDS)`. A slow but alive stream is untouched; a
silent one raises `ProviderTimeoutError`, which the existing SSE path turns into an upstream
error frame followed by `[DONE]`, and the shielded `finally` still records usage for what was
delivered.

This is intentionally at the adapter, not the route: every provider that reads bytes should
enforce it, and the route cannot distinguish "slow model" from "dead connection".

### Workers stay gated

`GATEWAY_WORKERS` is wired into the container command, default 1, and documented as unsafe to
raise until G1.2 lands shared rate limiting, cooldown, and login throttling. The lever exists so
capacity testing can measure it; enabling it today would silently multiply per-process limits.

## Trade-offs and open gaps

- Pool sizing is still static per process; no adaptive pool or per-endpoint limits.
- Drain waits for streaming responses at their natural pace up to the grace window; there is no
  partial-content close protocol beyond emitting what was already sent.
- The idle timeout does not apply to the non-streaming path, which is already bounded by the
  total request timeout.
- `InFlightTracker` counts requests, not memory; a single enormous response is still one unit.
