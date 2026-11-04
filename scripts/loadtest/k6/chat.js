// Load profile for /v1/chat/completions.
//
// k6 buffers a response, so with STREAM=true the latency covers the whole SSE
// stream. Time to first token is measured by the gateway itself; read
// gateway_upstream_ttft_seconds from /metrics instead of trying to derive it here.
//
// Env: GATEWAY_URL, GATEWAY_KEY, GATEWAY_MODEL, STREAM, RATE, DURATION,
//      VUS, MAX_VUS, MAX_TOKENS, MAX_ERROR_RATE

import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const BASE = __ENV.GATEWAY_URL || 'http://127.0.0.1:4000';
const KEY = __ENV.GATEWAY_KEY;
const MODEL = __ENV.GATEWAY_MODEL || 'loadtest-model';
const STREAM = __ENV.STREAM === 'true';
const MAX_TOKENS = Number(__ENV.MAX_TOKENS || 32);

const chatLatency = new Trend('gateway_chat_latency', true);

export const options = {
  scenarios: {
    chat: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 20),
      timeUnit: '1s',
      duration: __ENV.DURATION || '60s',
      preAllocatedVUs: Number(__ENV.VUS || 50),
      maxVUs: Number(__ENV.MAX_VUS || 500),
      tags: { mode: STREAM ? 'stream' : 'buffered' },
    },
  },
  thresholds: {
    http_req_failed: [`rate<${__ENV.MAX_ERROR_RATE || 0.01}`],
    gateway_chat_latency: [`p(95)<${__ENV.MAX_P95_MS || 5000}`],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const response = http.post(
    `${BASE}/v1/chat/completions`,
    JSON.stringify({
      model: MODEL,
      messages: [{ role: 'user', content: 'load test message' }],
      max_tokens: MAX_TOKENS,
      stream: STREAM,
    }),
    {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${KEY}`,
      },
      timeout: '180s',
      tags: { mode: STREAM ? 'stream' : 'buffered' },
    },
  );

  chatLatency.add(response.timings.duration);
  check(response, {
    'status is 200': (result) => result.status === 200,
  });
}
