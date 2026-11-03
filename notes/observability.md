# Observability: why tracing, and what `traceparent` is

Status: design note for TODO G0.5 (tracing) and the reasoning behind G0.4 (metrics).
Scope: gateway data plane. Metrics design is referenced but not specified here.

## 1. The problem

The gateway sits in the middle of a call chain: client -> gateway -> upstream provider,
plus asynchronous side paths (usage accounting, audit capture). Three questions cannot be
answered by the current telemetry:

1. **Which spans belong to one logical request?** A single `/v1/chat/completions` call can
   produce several upstream attempts (retries today, fallbacks later). Logs emit one line per
   attempt, but nothing states that attempt 2 is the same user request as attempt 1.
2. **Where did the latency go?** `request_context.py` records only total `duration_ms`.
   It cannot separate authentication, quota lookup, the month-total aggregate, the rate-limit
   upsert, the upstream time-to-first-token, and the streaming tail.
3. **Which request produced this row?** Usage and audit writes are shielded side effects.
   When `usage_record_failed` appears, there is no durable key linking it to the inference
   request, tenant, or the fallback that preceded it.

Enterprise requirements that depend on this: SLO attribution, billing dispute forensics,
noisy-tenant investigation, incident timelines.

## 2. Why traces, and what logs and metrics cannot do

- **Metrics** are aggregated. They answer "is the system healthy", not "why was this request
  slow or expensive". They also cannot carry per-request causality because request-scoped
  identifiers are forbidden as label values.
- **Logs** are events. They are excellent for "what happened here", but they carry no parent
  relationship and no duration decomposition across processes.
- **Traces** are the only structure that models causality and per-hop duration. A trace is
  also the natural join key between a log line, an upstream span, a usage row, and an
  audit row.

The three are complementary, not substitutes: metrics for alerting and autoscaling, logs for
detail, traces for causality.

## 3. What `traceparent` is

`traceparent` is the W3C Trace Context propagation header. It carries the identity of a
call chain across process and vendor boundaries. OpenTelemetry, Envoy, nginx, Azure OpenAI,
and common APMs all understand it.

Format: four dash-separated lowercase hex fields.

```
00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
 | |                                |                |
 | |                                |                +-- flags (1 byte): bit0 = sampled
 | |                                +------------------- parent-id (8 bytes)
 | +---------------------------------------------------- trace-id (16 bytes)
 +------------------------------------------------------ version
```

| Field | Meaning | Rules |
|---|---|---|
| `version` | spec version | `00` today; `ff` is invalid |
| `trace-id` | shared by every span in the chain | 16 bytes; all-zero invalid; never changes mid-chain |
| `parent-id` | the **caller's** span id | 8 bytes; all-zero invalid; changes on every hop |
| `flags` | 1 byte, bit0 = sampled | `01` sampled, `00` not sampled; other bits reserved |

Optional companion header `tracestate` carries vendor-specific state (max 32 entries,
left-most is most recent). Not needed for the first iteration.

Critical detail: **`parent-id` is the caller's span id, not the current span id.** Each
process parses the incoming header, keeps `trace-id`, and emits a new header whose
`parent-id` is its own span id.

```
trace-id = 4bf9...4736 (constant for the whole chain)

client   span A (span-id a1b2...)
  gateway span B (span-id c3d4...)   <- header to upstream: 00-4bf9...-c3d4...-01
     DB lookup      span C
     upstream try 1 span D
     upstream try 2 span E            <- both D and E are children of B
     usage write    span F
```

D and E sharing parent B is exactly the relationship the current logs cannot express.

## 4. Decisions

### 4.1 Manual spans, not auto-instrumentation packages

Considered: `opentelemetry-instrumentation-fastapi` / `-httpx` / `-sqlalchemy`.

Rejected for the data plane:
- The upstream header must be produced per attempt and per retry. Auto-instrumentation
  creates one span per HTTP call but gives no control over the attempt attribute, TTFT, or
  the fallback grouping we need.
- Auto-instrumentation adds three dependencies and monkey-patches global state, which
  complicates tests that inject `httpx.AsyncClient` fakes.
- The explicit surface is small: one server span in the existing middleware, one client span
  in the provider adapter.

Accepted cost: no automatic DB spans. A manual span around usage/audit writes can be added
later if the write path becomes a bottleneck.

### 4.2 Dependency set

`opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`.
No instrumentation packages. The SDK is a normal dependency but its provider is only built
when tracing is enabled; with no provider installed, the API returns no-op spans.

### 4.3 Disabled by default

`GATEWAY_TRACING_ENABLED=false` is the default. When disabled:
- no provider is installed, so no span is recorded;
- no `traceparent` is emitted to upstreams, so upstream behavior is unchanged;
- the log formatter emits no `trace_id` field.

Enabling requires `GATEWAY_TRACING_ENDPOINT` (OTLP/HTTP). Enabling without an endpoint fails
at startup rather than silently dropping spans.

### 4.4 Header handling

Inbound:
- parse `traceparent`; accept only version `00`, lowercase hex, non-zero `trace-id` and
  `parent-id`;
- invalid or absent header -> start a new trace;
- honor the incoming sampled flag (a non-sampled upstream decision stays non-sampled).

Outbound:
- always generate a new `parent-id` (never re-emit the inbound header unchanged);
- propagate `flags` from the sampling decision made at the gateway;
- do not send `tracestate` in the first iteration.

The header is untrusted client input. It is used only for correlation, never for
authentication, tenancy, or authorization.

### 4.5 `trace_id` and `request_id` coexist

They are different keys and neither replaces the other:

| | `request_id` | `trace_id` |
|---|---|---|
| origin | gateway, but the client may supply it | trace root |
| guarantees | readable, stable, in every error envelope | globally unique, cross-process, parent/child |
| weakness | client-supplied, may repeat or be forged | absent when the request is not sampled |

`request_id` stays the user-facing and log-grep key. `trace_id` is the join key across
gateway, upstream, and persistence, and is written into `usage_records` and
`audit_requests` as a nullable column.

### 4.6 Sampling

Head-based sampling at the gateway, `GATEWAY_TRACING_SAMPLE_RATIO` in `[0, 1]`, wrapped in
`ParentBased` so an upstream decision is honored. Errors and slow requests should eventually
be force-sampled; that is tail-based sampling and is explicitly out of scope for the first
iteration. Until it lands, operators should raise the ratio when investigating.

### 4.7 Span attributes

Server span (`http.server`):
`http.request.method`, `url.path`, `http.response.status_code`, `llm.tenant_id`,
`llm.api_key_id`, `llm.model_id`. No prompts, completions, keys, or request bodies.

Client span (`llm.upstream`), one per attempt:
`llm.provider`, `llm.model_id`, `llm.upstream_model`, `llm.attempt`, `llm.stream`,
`http.response.status_code`, `llm.ttft_ms` (streaming only), plus the exception type on
failure. Span name is `<provider> chat`; retries are siblings, not children, so parallel
attempts never appear falsely sequential.

`llm.ttft_ms` is the metric the system is currently missing entirely, and it is the most
important latency number for an LLM gateway.

## 5. Metrics

Metrics answer a different question than traces: "is the system healthy, and did it get
worse", aggregated over time and app instances. They are not a substitute for traces and
traces are not a substitute for them.

Decisions:

- **Prometheus, separate port.** Scraping is the dominant pattern for self-hosted gateways.
  The endpoint binds `GATEWAY_METRICS_HOST:GATEWAY_METRICS_PORT` and defaults to loopback, so
  enabling it never widens the inference API surface. A failed bind logs
  `metrics_endpoint_bind_failed` and continues serving traffic.
- **Narrow labels only.** `provider`, `model`, `route` template, `status_code`, `error`
  class, rejection reason. Never tenant, key, request id, prompt, completion, or a concrete
  path. Route labels come from the matched route template; unmatched requests collapse to
  `unmatched`, which also removes a cardinality attack vector.
- **TTFT is a histogram, not only a span attribute.** A trace holds one request's value; a
  histogram is what makes P50/P95 queryable. The same applies to request and upstream
  duration.
- **Instruments are process-global and thread-safe.** They are created once and replaced at
  startup; with no provider installed they are no-ops, so importing a call site is always
  safe and tests never need a live endpoint.
- **No per-attempt spans required for metrics.** Upstream counters carry `status`, so retries
  are visible as two increments with different statuses even without a trace backend.

Not covered in the first iteration: database pool occupancy, queue depth, per-provider
budget gauges, dashboard JSON, alert rules, and OTLP metric export.

## 6. Consequences

Positive:
- retries and fallbacks become explainable;
- latency splits into gateway overhead, upstream TTFT, and stream tail;
- billing and audit rows become traceable to a call chain;
- one join key (`trace_id`) links logs, traces, and database records.

Negative:
- one nullable column per persisted table, plus a migration;
- sampling means some requests have no trace (by design; `request_id` still covers them);
- explicit spans are code we own and must keep in sync with new call paths;
- an unreachable OTLP collector must never block requests: export is batched and
  fire-and-forget, and shutdown must flush with a bounded timeout.

## 7. Rollout

1. Config + telemetry module + server span + `trace_id` in JSON logs. Done.
2. Client spans with attempt/TTFT/status attributes and outbound `traceparent`. Done.
3. Nullable `trace_id` on `usage_records` and `audit_requests` + migration `0006`. Done.
4. Prometheus metrics with narrow labels and TTFT histograms (TODO G0.4). Done.
5. Later: database pool metrics, DB write spans, tail sampling, dashboards and alerts.

## 8. References

- W3C Trace Context: https://www.w3.org/TR/trace-context/
- OpenTelemetry Python SDK and OTLP/HTTP exporter
- `src/llm_gateway/request_context.py` (existing middleware and access log)
- `src/llm_gateway/providers/openai.py` (retry loop that must stay inside one trace)

