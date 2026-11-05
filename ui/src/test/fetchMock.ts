import { vi, type Mock } from 'vitest';

import type { AdminActorType, AdminRole } from '../lib/session';

export type RouteHandler = (url: URL, init: RequestInit) => Response | Promise<Response>;

export interface Routes {
  '/healthz'?: RouteHandler;
  '/readyz'?: RouteHandler;
  'POST /api/v1/auth/login'?: RouteHandler;
  'POST /api/v1/auth/logout'?: RouteHandler;
  '/api/v1/auth/me'?: RouteHandler;
  '/api/v1/models'?: RouteHandler;
  'POST /api/v1/models'?: RouteHandler;
  'DELETE /api/v1/models/:id'?: RouteHandler;
  'GET /api/v1/models/:id/deployments'?: RouteHandler;
  'POST /api/v1/models/:id/deployments'?: RouteHandler;
  'PATCH /api/v1/deployments/:id'?: RouteHandler;
  'DELETE /api/v1/deployments/:id'?: RouteHandler;
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
  'GET /api/v1/audit/export'?: RouteHandler;
  'DELETE /api/v1/audit'?: RouteHandler;
  '/api/v1/admins'?: RouteHandler;
  'POST /api/v1/admins'?: RouteHandler;
  'PATCH /api/v1/admins/:id'?: RouteHandler;
  '/api/v1/admin-audit'?: RouteHandler;
}

export const DEFAULT_ADMIN_USERNAME = 'owner';
export const DEFAULT_ADMIN_PASSWORD = 'correct-horse-battery';
export const DEFAULT_CSRF_TOKEN = 'test_csrf_token';
export const DEFAULT_ADMIN_ID = '11111111-1111-4111-8111-111111111111';

export interface MockSessionOptions {
  username?: string;
  displayName?: string;
  password?: string;
  role?: AdminRole;
  adminId?: string;
  csrfToken?: string;
}

interface MockSessionState {
  session: {
    username: string;
    displayName: string;
    role: AdminRole;
    adminId: string;
    csrfToken: string;
  } | null;
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

function errorResponse(
  status: number,
  code: string,
  message: string,
  requestId: string,
  type = 'authentication_error',
): Response {
  return jsonResponse(
    {
      error: {
        message,
        type,
        param: null,
        code,
        request_id: requestId,
      },
    },
    status,
    { 'x-request-id': requestId },
  );
}

function clearAdminCookies(): void {
  document.cookie = 'gw_admin_csrf=; Max-Age=0; path=/';
}

function setCsrfCookie(token: string): void {
  document.cookie = `gw_admin_csrf=${token}; path=/`;
}

export function readTestCsrfToken(): string | null {
  const prefix = 'gw_admin_csrf=';
  for (const chunk of document.cookie.split(';')) {
    const trimmed = chunk.trim();
    if (trimmed.startsWith(prefix)) return trimmed.slice(prefix.length);
  }
  return null;
}

function loginResponse(
  session: NonNullable<MockSessionState['session']>,
  actorType: AdminActorType = 'admin',
): Response {
  return jsonResponse({
    username: session.username,
    display_name: session.displayName,
    role: session.role,
    actor_type: actorType,
    expires_at: '2026-11-05T12:00:00Z',
  });
}

function createDefaultRoutes(
  state: MockSessionState,
  options: Required<MockSessionOptions>,
): Record<keyof Routes, RouteHandler> {
  return {
    '/healthz': () => jsonResponse({ status: 'ok', version: '0.1.0' }),
    '/readyz': () => jsonResponse({ status: 'ok', checks: { database: 'ok' } }),

    'POST /api/v1/auth/login': (_url, init) => {
      const body = JSON.parse(String(init.body ?? '{}')) as {
        username?: string;
        password?: string;
      };
      const username = (body.username ?? '').trim().toLowerCase();
      if (username !== options.username || body.password !== options.password) {
        return errorResponse(
          401,
          'invalid_credentials',
          'Invalid username or password',
          'req_invalid_credentials',
        );
      }
      state.session = {
        username: options.username,
        displayName: options.displayName,
        role: options.role,
        adminId: options.adminId,
        csrfToken: options.csrfToken,
      };
      setCsrfCookie(options.csrfToken);
      return loginResponse(state.session);
    },

    'POST /api/v1/auth/logout': () => {
      state.session = null;
      clearAdminCookies();
      return new Response(null, { status: 204 });
    },

    '/api/v1/auth/me': () => {
      if (state.session === null) {
        return errorResponse(
          401,
          'admin_auth_required',
          'Management authentication is required',
          'req_no_session',
        );
      }
      return jsonResponse({
        actor_type: 'admin',
        name: state.session.username,
        role: state.session.role,
        admin_id: state.session.adminId,
        session_expires_at: '2026-11-05T12:00:00Z',
      });
    },

    '/api/v1/models': () => jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }),
    'POST /api/v1/models': () => {
      throw new Error('Unexpected request: POST /api/v1/models');
    },
    'DELETE /api/v1/models/:id': () => {
      throw new Error('Unexpected request: DELETE /api/v1/models/:id');
    },
    'GET /api/v1/models/:id/deployments': (url) =>
      jsonResponse({
        model_id: decodeURIComponent(url.pathname.split('/')[4] ?? ''),
        items: [],
      }),
    'POST /api/v1/models/:id/deployments': () => {
      throw new Error('Unexpected request: POST /api/v1/models/:id/deployments');
    },
    'PATCH /api/v1/deployments/:id': () => {
      throw new Error('Unexpected request: PATCH /api/v1/deployments/:id');
    },
    'DELETE /api/v1/deployments/:id': () => {
      throw new Error('Unexpected request: DELETE /api/v1/deployments/:id');
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
        covered_tokens: 0,
        billable_tokens: 0,
        list_cost: '0.000000',
        billed_cost: '0.000000',
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
    'GET /api/v1/audit/export': () => {
      throw new Error('Unexpected request: GET /api/v1/audit/export');
    },
    'DELETE /api/v1/audit': () => {
      throw new Error('Unexpected request: DELETE /api/v1/audit');
    },
    '/api/v1/admins': (url) =>
      jsonResponse({
        items: [],
        total: 0,
        limit: Number(url.searchParams.get('limit') ?? '50'),
        offset: Number(url.searchParams.get('offset') ?? '0'),
      }),
    'POST /api/v1/admins': () => {
      throw new Error('Unexpected request: POST /api/v1/admins');
    },
    'PATCH /api/v1/admins/:id': () => {
      throw new Error('Unexpected request: PATCH /api/v1/admins/:id');
    },
    '/api/v1/admin-audit': (url) =>
      jsonResponse({
        items: [],
        total: 0,
        limit: Number(url.searchParams.get('limit') ?? '25'),
        offset: Number(url.searchParams.get('offset') ?? '0'),
      }),
  };
}

function resolveHandler(routes: Routes, url: URL, init: RequestInit): RouteHandler | undefined {
  const method = (init.method ?? 'GET').toUpperCase();

  if (/^\/api\/v1\/models\/[^/]+\/deployments$/.test(url.pathname)) {
    const handler =
      method === 'POST'
        ? routes['POST /api/v1/models/:id/deployments']
        : method === 'GET'
          ? routes['GET /api/v1/models/:id/deployments']
          : undefined;
    if (handler !== undefined) return handler;
  }

  if (method === 'PATCH' && /^\/api\/v1\/deployments\/[^/]+$/.test(url.pathname)) {
    const handler = routes['PATCH /api/v1/deployments/:id'];
    if (handler !== undefined) return handler;
  }

  if (method === 'DELETE' && /^\/api\/v1\/deployments\/[^/]+$/.test(url.pathname)) {
    const handler = routes['DELETE /api/v1/deployments/:id'];
    if (handler !== undefined) return handler;
  }

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

  if (method === 'PATCH' && /^\/api\/v1\/admins\/[^/]+$/.test(url.pathname)) {
    const handler = routes['PATCH /api/v1/admins/:id'];
    if (handler !== undefined) return handler;
  }

  const methodKey = `${method} ${url.pathname}` as keyof Routes;
  const methodHandler = routes[methodKey];
  if (methodHandler !== undefined) return methodHandler;

  return routes[url.pathname as keyof Routes];
}

export function installFetchMock(
  overrides: Routes = {},
  sessionOptions: MockSessionOptions = {},
): Mock<typeof fetch> {
  clearAdminCookies();
  const options: Required<MockSessionOptions> = {
    username: sessionOptions.username ?? DEFAULT_ADMIN_USERNAME,
    displayName: sessionOptions.displayName ?? 'Owner',
    password: sessionOptions.password ?? DEFAULT_ADMIN_PASSWORD,
    role: sessionOptions.role ?? 'owner',
    adminId: sessionOptions.adminId ?? DEFAULT_ADMIN_ID,
    csrfToken: sessionOptions.csrfToken ?? DEFAULT_CSRF_TOKEN,
  };
  const state: MockSessionState = { session: null };
  const routes = { ...createDefaultRoutes(state, options), ...overrides };

  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = toUrl(input);
    const requestInit = init ?? {};
    const method = (requestInit.method ?? 'GET').toUpperCase();
    const handler = resolveHandler(routes, url, requestInit);
    if (handler === undefined) {
      throw new Error(`Unexpected request: ${url.pathname}`);
    }

    if (url.pathname.startsWith('/api/v1/')) {
      if (url.pathname === '/api/v1/auth/login' && method === 'POST') {
        return handler(url, requestInit);
      }

      if (state.session === null) {
        return errorResponse(
          401,
          'admin_auth_required',
          'Management authentication is required',
          'req_mock_no_session',
        );
      }

      if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(method)) {
        const csrf = new Headers(requestInit.headers).get('x-csrf-token');
        if (csrf !== state.session.csrfToken) {
          return errorResponse(
            403,
            'csrf_failed',
            'The CSRF token is missing or invalid',
            'req_mock_csrf',
            'permission_error',
          );
        }
      }
    }

    return handler(url, requestInit);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
