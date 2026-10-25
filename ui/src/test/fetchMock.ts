import { vi, type Mock } from 'vitest';

export type RouteHandler = (url: URL, init: RequestInit) => Response | Promise<Response>;

export interface Routes {
  '/healthz'?: RouteHandler;
  '/readyz'?: RouteHandler;
  '/api/v1/models'?: RouteHandler;
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
};

export function installFetchMock(overrides: Routes = {}): Mock<typeof fetch> {
  const routes = { ...defaultRoutes, ...overrides };
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = toUrl(input);
    const handler = routes[url.pathname as keyof Routes];
    if (handler === undefined) {
      throw new Error(`Unexpected request: ${url.pathname}`);
    }
    return handler(url, init ?? {});
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
