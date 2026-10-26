import { vi, type Mock } from 'vitest';

export type RouteHandler = (url: URL, init: RequestInit) => Response | Promise<Response>;

export interface Routes {
  '/healthz'?: RouteHandler;
  '/readyz'?: RouteHandler;
  '/api/v1/models'?: RouteHandler;
  '/api/v1/tenants'?: RouteHandler;
  'POST /api/v1/tenants'?: RouteHandler;
  'PATCH /api/v1/tenants/:id'?: RouteHandler;
  '/api/v1/usage/summary'?: RouteHandler;
  '/api/v1/usage/series'?: RouteHandler;
  '/api/v1/usage/by-key'?: RouteHandler;
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
  '/api/v1/tenants': () => jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }),
  'POST /api/v1/tenants': () => {
    throw new Error('Unexpected request: POST /api/v1/tenants');
  },
  'PATCH /api/v1/tenants/:id': () => {
    throw new Error('Unexpected request: PATCH /api/v1/tenants/:id');
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
};

function resolveHandler(routes: Routes, url: URL, init: RequestInit): RouteHandler | undefined {
  const method = (init.method ?? 'GET').toUpperCase();

  if (method === 'PATCH' && url.pathname.startsWith('/api/v1/tenants/')) {
    const handler = routes['PATCH /api/v1/tenants/:id'];
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
    const handler = resolveHandler(routes, url, init ?? {});
    if (handler === undefined) {
      throw new Error(`Unexpected request: ${url.pathname}`);
    }
    return handler(url, init ?? {});
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
