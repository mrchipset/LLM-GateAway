import { vi, type Mock } from 'vitest';

export type RouteHandler = (url: URL, init: RequestInit) => Response | Promise<Response>;

export interface Routes {
  '/healthz'?: RouteHandler;
  '/readyz'?: RouteHandler;
  '/api/v1/models'?: RouteHandler;
  'POST /api/v1/models'?: RouteHandler;
  'DELETE /api/v1/models/:id'?: RouteHandler;
  'GET /api/v1/models/:id/prices'?: RouteHandler;
  'POST /api/v1/models/:id/prices'?: RouteHandler;
  '/api/v1/tenants'?: RouteHandler;
  'POST /api/v1/tenants'?: RouteHandler;
  'PATCH /api/v1/tenants/:id'?: RouteHandler;
  'GET /api/v1/tenants/:id/billing'?: RouteHandler;
  'GET /api/v1/tenants/:id/model-access'?: RouteHandler;
  'PUT /api/v1/tenants/:id/model-access'?: RouteHandler;
  '/api/v1/keys'?: RouteHandler;
  'POST /api/v1/keys'?: RouteHandler;
  'DELETE /api/v1/keys/:id'?: RouteHandler;
  '/api/v1/usage/summary'?: RouteHandler;
  '/api/v1/usage/series'?: RouteHandler;
  '/api/v1/usage/by-key'?: RouteHandler;
  '/api/v1/audit/sessions'?: RouteHandler;
  'GET /api/v1/audit/sessions/:id'?: RouteHandler;
  'GET /api/v1/audit/requests/:id'?: RouteHandler;
}

export function toUrl(input: RequestInfo | URL): URL {
  if (typeof input === 'string') return new URL(input, 'http://localhost');
  if (input instanceof URL) return input;
  return new URL(input.url, 'http://localhost');
}

export function jsonResponse(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

const defaultRoutes: Record<keyof Routes, RouteHandler> = {
  '/healthz': () => jsonResponse({ status: 'ok', version: '0.1.0' }),
  '/readyz': () => jsonResponse({ status: 'ok', checks: { database: 'ok' } }),
  '/api/v1/models': () => jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }),
  'POST /api/v1/models': () => {
    throw new Error('Unexpected request: POST /api/v1/models');
  },
  'DELETE /api/v1/models/:id': () => {
    throw new Error('Unexpected request: DELETE /api/v1/models/:id');
  },
  'GET /api/v1/models/:id/prices': () =>
    jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }),
  'POST /api/v1/models/:id/prices': () => {
    throw new Error('Unexpected request: POST /api/v1/models/:id/prices');
  },
  '/api/v1/tenants': () => jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }),
  'POST /api/v1/tenants': () => {
    throw new Error('Unexpected request: POST /api/v1/tenants');
  },
  'PATCH /api/v1/tenants/:id': () => {
    throw new Error('Unexpected request: PATCH /api/v1/tenants/:id');
  },
  'GET /api/v1/tenants/:id/billing': () =>
    jsonResponse({
      tenant_id: 'tenant',
      currency: 'USD',
      period_start: '2026-10-01T00:00:00Z',
      period_end: '2026-11-01T00:00:00Z',
      plan_tokens: null,
      plan_allow_overage: false,
      monthly_cost_budget: null,
      used_tokens: 0,
      covered_tokens: 0,
      billable_tokens: 0,
      requests: 0,
      list_cost: '0.000000',
      billed_cost: '0.000000',
      budget_remaining: null,
    }),
  'GET /api/v1/tenants/:id/model-access': () => {
    throw new Error('Unexpected request: GET /api/v1/tenants/:id/model-access');
  },
  'PUT /api/v1/tenants/:id/model-access': () => {
    throw new Error('Unexpected request: PUT /api/v1/tenants/:id/model-access');
  },
  '/api/v1/keys': () =>
    jsonResponse({ items: [], total: 0, limit: 20, offset: 0, tenant_id: null }),
  'POST /api/v1/keys': () => {
    throw new Error('Unexpected request: POST /api/v1/keys');
  },
  'DELETE /api/v1/keys/:id': () => {
    throw new Error('Unexpected request: DELETE /api/v1/keys/:id');
  },
  '/api/v1/usage/summary': () =>
    jsonResponse({
      prompt_tokens: 0,
      completion_tokens: 0,
      cached_tokens: 0,
      total_tokens: 0,
      requests: 0,
      by_model: [],
    }),
  '/api/v1/usage/series': () => jsonResponse({ bucket: 'day', points: [] }),
  '/api/v1/usage/by-key': () => jsonResponse({ limit: 100, items: [] }),
  '/api/v1/audit/sessions': (url) =>
    jsonResponse({
      items: [],
      total: 0,
      limit: Number(url.searchParams.get('limit') ?? '20'),
      offset: Number(url.searchParams.get('offset') ?? '0'),
    }),
  'GET /api/v1/audit/sessions/:id': () =>
    jsonResponse(
      {
        error: {
          message: 'Audit session was not found',
          type: 'invalid_request_error',
          param: 'session_id',
          code: 'audit_session_not_found',
          request_id: 'req_audit_session_not_found',
        },
      },
      404,
      { 'x-request-id': 'req_audit_session_not_found' },
    ),
  'GET /api/v1/audit/requests/:id': () =>
    jsonResponse(
      {
        error: {
          message: 'Audit request was not found',
          type: 'invalid_request_error',
          param: 'request_id',
          code: 'audit_request_not_found',
          request_id: 'req_audit_request_not_found',
        },
      },
      404,
      { 'x-request-id': 'req_audit_request_not_found' },
    ),
};

function resolveHandler(routes: Routes, url: URL, init: RequestInit): RouteHandler | undefined {
  const method = (init.method ?? 'GET').toUpperCase();

  if (/^\/api\/v1\/models\/[^/]+\/prices$/.test(url.pathname)) {
    const handler =
      method === 'POST'
        ? routes['POST /api/v1/models/:id/prices']
        : method === 'GET'
          ? routes['GET /api/v1/models/:id/prices']
          : undefined;
    if (handler !== undefined) return handler;
  }

  if (method === 'GET' && /^\/api\/v1\/tenants\/[^/]+\/billing$/.test(url.pathname)) {
    const handler = routes['GET /api/v1/tenants/:id/billing'];
    if (handler !== undefined) return handler;
  }

  if (method === 'PATCH' && url.pathname.startsWith('/api/v1/tenants/')) {
    const handler = routes['PATCH /api/v1/tenants/:id'];
    if (handler !== undefined) return handler;
  }

  if (/^\/api\/v1\/tenants\/[^/]+\/model-access$/.test(url.pathname)) {
    const handler =
      method === 'PUT'
        ? routes['PUT /api/v1/tenants/:id/model-access']
        : method === 'GET'
          ? routes['GET /api/v1/tenants/:id/model-access']
          : undefined;
    if (handler !== undefined) return handler;
  }

  if (method === 'DELETE' && url.pathname.startsWith('/api/v1/models/')) {
    const handler = routes['DELETE /api/v1/models/:id'];
    if (handler !== undefined) return handler;
  }

  if (method === 'DELETE' && url.pathname.startsWith('/api/v1/keys/')) {
    const handler = routes['DELETE /api/v1/keys/:id'];
    if (handler !== undefined) return handler;
  }

  if (method === 'GET' && url.pathname.startsWith('/api/v1/audit/sessions/')) {
    const handler = routes['GET /api/v1/audit/sessions/:id'];
    if (handler !== undefined) return handler;
  }

  if (method === 'GET' && url.pathname.startsWith('/api/v1/audit/requests/')) {
    const handler = routes['GET /api/v1/audit/requests/:id'];
    if (handler !== undefined) return handler;
  }

  const methodKey = `${method} ${url.pathname}` as keyof Routes;
  const methodHandler = routes[methodKey];
  if (methodHandler !== undefined) return methodHandler;

  return routes[url.pathname as keyof Routes];
}

export function installFetchMock(overrides: Routes = {}): Mock<typeof fetch> {
  const routes = { ...defaultRoutes, ...overrides };
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = toUrl(input);
    const requestInit = init ?? {};
    const handler = resolveHandler(routes, url, requestInit);
    if (handler === undefined) {
      throw new Error(`Unexpected request: ${url.pathname}`);
    }

    if (url.pathname.startsWith('/api/v1/')) {
      const authorization = new Headers(requestInit.headers).get('Authorization');
      if (authorization === null) {
        return jsonResponse(
          {
            error: {
              message: 'A master key is required',
              type: 'authentication_error',
              param: null,
              code: 'invalid_api_key',
              request_id: 'req_mock_unauthorized',
            },
          },
          401,
          { 'x-request-id': 'req_mock_unauthorized' },
        );
      }
    }

    return handler(url, requestInit);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
