# Upstream prefill and decode throughput

## Problem

Operators need to tell "the upstream got slower" apart from "the gateway got slower", and to
compare models and providers. The gateway already records total upstream duration and
time-to-first-token, but a single TTFT number cannot separate prompt processing from token
generation, and a total duration mixes both with client behavior.

## What the gateway can actually observe

The OpenAI-compatible protocol exposes no engine timings. At the adapter boundary there are
only three useful timestamps and two token counts:

- request start, first streamed chunk, end of stream
- `prompt_tokens` (optionally with `prompt_tokens_details.cached_tokens`)
- `completion_tokens`

Therefore the gateway records *effective* rates, not engine-internal ones:

```
prefill_tokens_per_second = (prompt_tokens - cached_tokens) / ttft_seconds
decode_tokens_per_second  = (completion_tokens - 1) / (end_of_stream - first_chunk)
```

`completion_tokens - 1` because the first token is produced at the end of prefill and is already
counted inside TTFT. Cached prompt tokens are excluded when the provider reports them: they were
not prefilled, and including them inflates the rate by orders of magnitude for cache hits.

## Decisions

- Two histograms, `gateway_upstream_prefill_tokens_per_second` and
  `gateway_upstream_decode_tokens_per_second`, labelled by `provider` and `model` only.
  Buckets span 1 to 5000 token/s; the default second-oriented buckets would be useless here.
- Recorded inside the streaming loop of each adapter (`openai.py`, `anthropic.py`), the only place
  that sees the first-chunk timestamp and the final usage chunk. The shared math lives in
  `providers/throughput.py` so both adapters stay identical.
- Span attributes `llm.prefill_tokens_per_second` and `llm.decode_tokens_per_second` mirror the
  histograms for per-request traces.
- Record only on successful completion. A cancelled or failed stream has no reliable token count.

## Limitations

- Non-streaming requests record neither metric: the response arrives as one payload, so there is
  no first-token timestamp to split prefill from decode.
- TTFT includes connection setup, upstream queueing, and network latency, so prefill throughput is
  a lower bound. A slow upstream queue makes prefill look slow even if the engine is fast.
- Decode throughput is measured at the gateway. A slow client applies backpressure through the
  stream, which lengthens the interval and lowers the measured rate.
- Usage may arrive in a final chunk after the last content token; the interval includes that
  finalization hop.
- These are not substitutes for engine metrics (vLLM/SGLang expose queue depth, KV cache usage,
  and true prefill/decode timings). They answer "is the upstream slowing down as seen by the
  gateway" without scraping each engine.

## Console display

`GET /api/v1/throughput` exposes the same rolling window to the admin console: per
provider/model P50 and P95 for both rates, the sample count, and the last observation. Any
authenticated admin may read it. The window is in-process, 15 minutes, at most 120 samples per
model; a multi-worker deployment returns the values collected by the worker that served the
request, which the console labels as "measured by this worker". The window is independent of
Prometheus: it works even when metrics export is disabled.

## Tests

- `tests/test_throughput.py`: formulas, cached-token exclusion, degenerate windows, missing usage,
  window aggregation and retention.
- `tests/test_admin_throughput.py`: authentication and the API response shape.
- `tests/test_metrics.py`: a streamed response with a usage chunk produces one sample in each
  histogram; a non-streaming response produces none.
