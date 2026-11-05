import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ApiKeySummary, TenantLimitsPatch, TenantSummary } from '../api/client';
import { signIn } from './signIn';
import {
  DEFAULT_ADMIN_PASSWORD,
  installFetchMock,
  jsonResponse,
  readTestCsrfToken,
  toUrl,
  type Routes,
} from './fetchMock';
import { renderApp } from './renderApp';

const FIXED_NOW = new Date('2026-10-25T12:00:00.000Z');
const PAGE_SIZE = 20;

const ACME: TenantSummary = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Acme',
  created_at: '2026-09-01T00:00:00Z',
  monthly_token_quota: 1_000_000,
  plan_tokens: null,
  plan_allow_overage: false,
  monthly_cost_budget: null,
  requests_per_minute: 60,
  audit_enabled: false,
  model_access_mode: 'all',
};

const SOLO: TenantSummary = {
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Solo',
  created_at: '2026-09-02T00:00:00Z',
  monthly_token_quota: null,
  plan_tokens: null,
  plan_allow_overage: false,
  monthly_cost_budget: null,
  requests_per_minute: null,
  audit_enabled: false,
  model_access_mode: 'all',
};

const TENANTS = [ACME, SOLO];

const PRODUCTION_KEY: ApiKeySummary = {
  id: 'aaaaaaaa-1111-4111-8111-111111111111',
  tenant_id: ACME.id,
  name: 'Production',
  key_prefix: 'lgw_live_prod',
  created_at: '2026-10-01T08:15:00Z',
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
};

const MANY_TENANTS: TenantSummary[] = Array.from({ length: 105 }, (_, index) => ({
  id: `${String(index + 1).padStart(8, '0')}-1111-4111-8111-111111111111`,
  name: `Tenant ${index + 1}`,
  created_at: '2026-09-01T00:00:00Z',
  monthly_token_quota: null,
  plan_tokens: null,
  plan_allow_overage: false,
  monthly_cost_budget: null,
  requests_per_minute: null,
  audit_enabled: false,
  model_access_mode: 'all',
}));

function pageResponse(tenants: TenantSummary[], url: URL): Response {
  const limit = Number(url.searchParams.get('limit') ?? '100');
  const offset = Number(url.searchParams.get('offset') ?? '0');
  return jsonResponse({
    items: tenants.slice(offset, offset + limit),
    total: tenants.length,
    limit,
    offset,
  });
}

function installAccessMock(overrides: Routes = {}) {
  return installFetchMock({
    '/api/v1/tenants': (url) => pageResponse(TENANTS, url),
    ...overrides,
  });
}

function installEditableTenants(
  initial: TenantSummary[],
  patchResponse?: (args: { body: TenantLimitsPatch; tenant: TenantSummary }) => Response,
) {
  let tenants = initial.map((tenant) => ({ ...tenant }));
  const patchBodies: TenantLimitsPatch[] = [];
  const fetchMock = installFetchMock({
    '/api/v1/tenants': (url) => pageResponse(tenants, url),
    'PATCH /api/v1/tenants/:id': (url, init) => {
      const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
      const body = JSON.parse(String(init.body)) as TenantLimitsPatch;
      patchBodies.push(body);
      const existing = tenants.find((tenant) => tenant.id === id);
      if (existing === undefined) {
        return jsonResponse(
          {
            error: {
              message: `Tenant '${id}' was not found`,
              type: 'invalid_request_error',
              param: 'tenant_id',
              code: 'tenant_not_found',
              request_id: 'req_missing_tenant',
            },
          },
          404,
          { 'x-request-id': 'req_missing_tenant' },
        );
      }

      if (patchResponse !== undefined) {
        return patchResponse({ body, tenant: existing });
      }

      const updated: TenantSummary = { ...existing };
      if (body.name !== undefined) {
        updated.name = body.name;
      }
      if (body.monthly_token_quota !== undefined) {
        updated.monthly_token_quota = body.monthly_token_quota;
      }
      if (body.requests_per_minute !== undefined) {
        updated.requests_per_minute = body.requests_per_minute;
      }
      if (body.audit_enabled !== undefined) {
        updated.audit_enabled = body.audit_enabled;
      }
      tenants = tenants.map((tenant) => (tenant.id === id ? updated : tenant));
      return jsonResponse(updated);
    },
  });

  return { fetchMock, patchBodies };
}

function tenantGetCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return url.pathname === '/api/v1/tenants' && (init?.method ?? 'GET').toUpperCase() === 'GET';
  });
}

function keyGetCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return url.pathname === '/api/v1/keys' && (init?.method ?? 'GET').toUpperCase() === 'GET';
  });
}

function accessPageCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return tenantGetCalls(fetchMock).filter(
    ([input]) => toUrl(input).searchParams.get('limit') === String(PAGE_SIZE),
  );
}

function createTenantCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return url.pathname === '/api/v1/tenants' && (init?.method ?? 'GET').toUpperCase() === 'POST';
  });
}

function tenantRegion() {
  return screen.getByRole('region', { name: 'Tenants' });
}

async function openAccess(user: ReturnType<typeof userEvent.setup>) {
  await signIn(user);
  await user.click(await screen.findByRole('tab', { name: 'Access' }));
  await screen.findByRole('heading', { name: 'Tenants' });
}

describe('tenant management', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(FIXED_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.style.overflow = '';
  });

  it('does not request tenants before sign-in', async () => {
    const fetchMock = installFetchMock();
    renderApp();

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(tenantGetCalls(fetchMock)).toHaveLength(0);
  });

  it('renders tenant names, short ids, created times, limits, and total', async () => {
    installAccessMock();
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);

    const region = tenantRegion();
    const table = await screen.findByRole('table', { name: 'Tenants' });

    expect(await within(region).findByText('2 tenants')).toBeInTheDocument();
    expect(within(table).getByText('Acme')).toBeInTheDocument();
    expect(within(table).getByText('Solo')).toBeInTheDocument();
    expect(within(table).getByText('11111111…')).toBeInTheDocument();
    expect(within(table).getByText('Sep 01, 2026, 00:00 UTC')).toBeInTheDocument();
    expect(within(table).getByText('1,000,000/mo')).toBeInTheDocument();
    expect(within(table).getByText('60/min')).toBeInTheDocument();
    expect(within(table).getByText('Tokens')).toBeInTheDocument();
    expect(within(table).getByText('Rate')).toBeInTheDocument();
    expect(within(table).getByText('1,000,000 tokens per month')).toBeInTheDocument();
    expect(within(table).getByText('60 requests per minute')).toBeInTheDocument();
    expect(within(table).queryByText('1,000,000 tokens/month')).not.toBeInTheDocument();
    expect(within(table).getByText('No limits')).toBeInTheDocument();
  });

  it('shows a loading skeleton while the tenant page loads', async () => {
    let resolvePage: (response: Response) => void = () => {};
    const pendingPage = new Promise<Response>((resolve) => {
      resolvePage = resolve;
    });
    installFetchMock({
      '/api/v1/tenants': (url) =>
        url.searchParams.get('limit') === String(PAGE_SIZE)
          ? pendingPage
          : jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }),
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);

    const region = tenantRegion();
    expect(await within(region).findByText('Loading tenants…')).toBeInTheDocument();

    await act(async () => {
      resolvePage(jsonResponse({ items: TENANTS, total: TENANTS.length, limit: 20, offset: 0 }));
    });

    expect(await screen.findByRole('table', { name: 'Tenants' })).toBeInTheDocument();
  });

  it('shows an empty state when there are no tenants', async () => {
    installAccessMock({
      '/api/v1/tenants': (url) => pageResponse([], url),
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);

    const region = tenantRegion();
    expect(await within(region).findByText('0 tenants')).toBeInTheDocument();
    expect(within(region).getByText('No tenants yet')).toBeInTheDocument();
    expect(within(region).queryByRole('table', { name: 'Tenants' })).not.toBeInTheDocument();
  });

  it('shows the HTTP status, message, code, and request id when tenant loading fails', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) =>
        url.searchParams.get('limit') === String(PAGE_SIZE)
          ? jsonResponse(
              {
                error: {
                  message: 'Tenant store unavailable',
                  type: 'server_error',
                  param: null,
                  code: 'tenant_store_unavailable',
                  request_id: 'req_tenants_500',
                },
              },
              500,
              { 'x-request-id': 'req_tenants_500' },
            )
          : jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }),
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);

    const region = tenantRegion();
    expect(await within(region).findByText('Could not load tenants')).toBeInTheDocument();
    expect(within(region).getByText('HTTP 500')).toBeInTheDocument();
    expect(within(region).getByText('Tenant store unavailable')).toBeInTheDocument();
    expect(within(region).getByText('tenant_store_unavailable')).toBeInTheDocument();
    expect(within(region).getByText('req_tenants_500')).toBeInTheDocument();

    const before = accessPageCalls(fetchMock).length;
    await user.click(within(region).getByRole('button', { name: 'Retry loading tenants' }));

    await waitFor(() => {
      expect(accessPageCalls(fetchMock).length).toBeGreaterThan(before);
    });
  });

  it('refreshes the tenant page and shows a UTC last-updated time', async () => {
    const fetchMock = installAccessMock();
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    await screen.findByRole('table', { name: 'Tenants' });

    const region = tenantRegion();
    expect(await within(region).findByText('Updated 12:00:00 UTC')).toBeInTheDocument();

    const before = accessPageCalls(fetchMock).length;
    await user.click(within(region).getByRole('button', { name: 'Refresh tenants' }));

    await waitFor(() => {
      expect(accessPageCalls(fetchMock).length).toBeGreaterThan(before);
    });
  });

  it('creates a tenant with only a name and refreshes the list', async () => {
    let tenants = [...TENANTS];
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => pageResponse(tenants, url),
      'POST /api/v1/tenants': (_url, init) => {
        const body = JSON.parse(String(init.body)) as { name: string };
        const created: TenantSummary = {
          id: '33333333-3333-4333-8333-333333333333',
          name: body.name,
          created_at: '2026-10-25T12:00:00Z',
          monthly_token_quota: null,
          plan_tokens: null,
          plan_allow_overage: false,
          monthly_cost_budget: null,
          requests_per_minute: null,
          audit_enabled: false,
          model_access_mode: 'all',
        };
        tenants = [created, ...tenants];
        return jsonResponse(created, 201);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    const nameInput = within(region).getByLabelText('Tenant name');

    await user.type(nameInput, '  New Tenant  ');
    await user.click(within(region).getByRole('button', { name: 'Create tenant' }));

    expect(await within(region).findByText('Tenant created.')).toBeInTheDocument();
    expect(within(region).getByLabelText('Tenant name')).toHaveValue('');
    expect(await within(region).findByText('3 tenants')).toBeInTheDocument();

    const table = await screen.findByRole('table', { name: 'Tenants' });
    expect(within(table).getByText('New Tenant')).toBeInTheDocument();

    const createCalls = createTenantCalls(fetchMock);
    expect(createCalls).toHaveLength(1);
    const call = createCalls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;
    const [, init] = call;
    expect(JSON.parse(String(init?.body))).toEqual({ name: 'New Tenant' });
    expect(new Headers(init?.headers).get('x-csrf-token')).toBe(readTestCsrfToken());

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).not.toContain('gw_admin_session');
    expect(document.body.textContent).not.toContain(DEFAULT_ADMIN_PASSWORD);

    await user.click(screen.getByRole('tab', { name: 'Usage' }));
    expect(await screen.findByRole('option', { name: 'New Tenant' })).toBeInTheDocument();
  });

  it('blocks blank and overlong tenant names before sending', async () => {
    const fetchMock = installAccessMock();
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    const nameInput = within(region).getByLabelText('Tenant name');
    const submit = within(region).getByRole('button', { name: 'Create tenant' });

    await user.type(nameInput, '   ');
    await user.click(submit);
    expect(await within(region).findByText('Enter a tenant name.')).toBeInTheDocument();
    expect(createTenantCalls(fetchMock)).toHaveLength(0);

    await user.clear(nameInput);
    await user.type(nameInput, 'a'.repeat(101));
    await user.click(submit);
    expect(await within(region).findByText('Use 100 characters or fewer.')).toBeInTheDocument();
    expect(createTenantCalls(fetchMock)).toHaveLength(0);
  });

  it('keeps the entered name and shows code and request id on a duplicate tenant', async () => {
    installAccessMock({
      'POST /api/v1/tenants': () =>
        jsonResponse(
          {
            error: {
              message: "Tenant 'Acme' already exists",
              type: 'invalid_request_error',
              param: 'name',
              code: 'duplicate_tenant',
              request_id: 'req_duplicate',
            },
          },
          409,
          { 'x-request-id': 'req_duplicate' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    const nameInput = within(region).getByLabelText('Tenant name');

    await user.type(nameInput, 'Acme');
    await user.click(within(region).getByRole('button', { name: 'Create tenant' }));

    expect(await within(region).findByText('Could not create tenant')).toBeInTheDocument();
    expect(within(region).getByText('HTTP 409')).toBeInTheDocument();
    expect(within(region).getByText("Tenant 'Acme' already exists")).toBeInTheDocument();
    expect(within(region).getByText('duplicate_tenant')).toBeInTheDocument();
    expect(within(region).getByText('req_duplicate')).toBeInTheDocument();
    expect(nameInput).toHaveValue('Acme');
    expect(within(region).getByRole('button', { name: 'Create tenant' })).toBeEnabled();
  });

  it('disables the create button while the request is pending', async () => {
    let resolveCreate: (response: Response) => void = () => {};
    const pendingCreate = new Promise<Response>((resolve) => {
      resolveCreate = resolve;
    });
    installAccessMock({
      'POST /api/v1/tenants': () => pendingCreate,
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    const nameInput = within(region).getByLabelText('Tenant name');
    const submit = within(region).getByRole('button', { name: 'Create tenant' });

    await user.type(nameInput, 'Slow Tenant');
    await user.click(submit);

    expect(submit).toBeDisabled();
    expect(nameInput).toBeDisabled();

    await act(async () => {
      resolveCreate(
        jsonResponse(
          {
            id: '44444444-4444-4444-8444-444444444444',
            name: 'Slow Tenant',
            created_at: '2026-10-25T12:00:00Z',
            monthly_token_quota: null,
            plan_tokens: null,
            plan_allow_overage: false,
            monthly_cost_budget: null,
            requests_per_minute: null,
            audit_enabled: false,
            model_access_mode: 'all',
          },
          201,
        ),
      );
    });

    expect(await within(region).findByText('Tenant created.')).toBeInTheDocument();
    expect(within(region).getByLabelText('Tenant name')).toHaveValue('');
  });

  it('requests tenant pages with limit 20 and the right offset', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => pageResponse(MANY_TENANTS, url),
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    expect(await within(region).findByText('105 tenants')).toBeInTheDocument();

    let table = await screen.findByRole('table', { name: 'Tenants' });
    expect(within(table).getAllByRole('rowheader')).toHaveLength(20);
    expect(within(region).getByText('Showing 1–20 of 105')).toBeInTheDocument();
    expect(within(region).getByRole('button', { name: 'Previous tenant page' })).toBeDisabled();
    expect(within(region).getByRole('button', { name: 'Next tenant page' })).toBeEnabled();

    const pages = [
      { text: 'Showing 21–40 of 105', first: 'Tenant 21', rows: 20 },
      { text: 'Showing 41–60 of 105', first: 'Tenant 41', rows: 20 },
      { text: 'Showing 61–80 of 105', first: 'Tenant 61', rows: 20 },
      { text: 'Showing 81–100 of 105', first: 'Tenant 81', rows: 20 },
      { text: 'Showing 101–105 of 105', first: 'Tenant 101', rows: 5 },
    ];

    for (const page of pages) {
      await user.click(within(region).getByRole('button', { name: 'Next tenant page' }));
      expect(await within(region).findByText(page.text)).toBeInTheDocument();
      table = await screen.findByRole('table', { name: 'Tenants' });
      expect(within(table).getAllByRole('rowheader')).toHaveLength(page.rows);
      expect(within(table).getByText(page.first)).toBeInTheDocument();
    }

    expect(within(region).getByRole('button', { name: 'Next tenant page' })).toBeDisabled();

    await user.click(within(region).getByRole('button', { name: 'Previous tenant page' }));
    expect(await within(region).findByText('Showing 81–100 of 105')).toBeInTheDocument();

    const offsets = accessPageCalls(fetchMock).map(
      ([input]) => toUrl(input).searchParams.get('offset') ?? '',
    );
    expect(offsets).toEqual(['0', '20', '40', '60', '80', '100', '80']);
  });

  it('sends only changed limits and refreshes the selected tenant', async () => {
    const { patchBodies } = installEditableTenants(TENANTS);
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    const quotaInput = within(dialog).getByLabelText('Monthly token quota');
    const rateInput = within(dialog).getByLabelText('Requests per minute');
    const nameInput = within(dialog).getByLabelText('Tenant name');

    expect(quotaInput).toHaveValue(1000000);
    expect(rateInput).toHaveValue(60);
    await waitFor(() => {
      expect(document.activeElement).toBe(nameInput);
    });

    await user.clear(rateInput);
    await user.type(rateInput, '120');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([{ requests_per_minute: 120 }]);
    expect(await within(region).findByText('Limits updated for Acme.')).toBeInTheDocument();

    await waitFor(() => {
      const updatedTable = within(region).getByRole('table', { name: 'Tenants' });
      const row = within(updatedTable).getByRole('row', { name: /Acme/ });
      expect(within(row).getByText('120/min')).toBeInTheDocument();
      expect(within(row).getByText('1,000,000/mo')).toBeInTheDocument();
    });

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).not.toContain('gw_admin_session');
    expect(document.body.textContent).not.toContain(DEFAULT_ADMIN_PASSWORD);
  });

  it('refreshes the Usage tenant selector after editing limits in Access', async () => {
    const { patchBodies } = installEditableTenants(TENANTS);
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    const rateInput = within(dialog).getByLabelText('Requests per minute');

    await user.clear(rateInput);
    await user.type(rateInput, '120');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([{ requests_per_minute: 120 }]);

    await user.click(screen.getByRole('tab', { name: 'Usage' }));
    const tenantSelect = await screen.findByLabelText('Tenant');
    await screen.findByRole('option', { name: 'Acme' });
    await user.selectOptions(tenantSelect, ACME.id);
    const limits = screen.getByRole('group', { name: 'Tenant limits' });
    expect(await within(limits).findByText('120 req/min')).toBeInTheDocument();
  });

  it('sends explicit nulls when both tenant limits are cleared', async () => {
    const { patchBodies } = installEditableTenants(TENANTS);
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });

    await user.clear(within(dialog).getByLabelText('Monthly token quota'));
    await user.clear(within(dialog).getByLabelText('Requests per minute'));
    expect(
      within(dialog).getByText('Will clear: monthly token quota and requests per minute.'),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([{ monthly_token_quota: null, requests_per_minute: null }]);

    await waitFor(() => {
      const updatedTable = within(region).getByRole('table', { name: 'Tenants' });
      const row = within(updatedTable).getByRole('row', { name: /Acme/ });
      expect(within(row).getByText('No limits')).toBeInTheDocument();
    });
  });

  it('rejects zero and negative limits without sending a request', async () => {
    const { patchBodies } = installEditableTenants(TENANTS);
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    const quotaInput = within(dialog).getByLabelText('Monthly token quota');
    const save = within(dialog).getByRole('button', { name: 'Save changes' });

    await user.clear(quotaInput);
    await user.type(quotaInput, '0');
    await user.click(save);
    expect(
      await within(dialog).findByText('Enter a whole number of 1 or more.'),
    ).toBeInTheDocument();

    await user.clear(quotaInput);
    await user.type(quotaInput, '-2');
    await user.click(save);
    expect(within(dialog).getByText('Enter a whole number of 1 or more.')).toBeInTheDocument();

    expect(patchBodies).toHaveLength(0);
    expect(screen.getByRole('dialog', { name: 'Edit tenant' })).toBeInTheDocument();
  });

  it.each([
    {
      status: 404,
      code: 'tenant_not_found',
      message: "Tenant '11111111-1111-4111-8111-111111111111' was not found",
      requestId: 'req_edit_404',
    },
    {
      status: 400,
      code: 'invalid_request_body',
      message: 'requests_per_minute must be greater than or equal to 1',
      requestId: 'req_edit_400',
    },
  ])(
    'keeps the edit dialog open on a $status tenant limits error',
    async ({ status, code, message, requestId }) => {
      const { patchBodies } = installEditableTenants(TENANTS, () =>
        jsonResponse(
          {
            error: {
              message,
              type: 'invalid_request_error',
              param: status === 404 ? 'tenant_id' : 'requests_per_minute',
              code,
              request_id: requestId,
            },
          },
          status,
          { 'x-request-id': requestId },
        ),
      );
      const user = userEvent.setup();
      renderApp();

      await openAccess(user);
      const table = await screen.findByRole('table', { name: 'Tenants' });

      await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
      const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
      const rateInput = within(dialog).getByLabelText('Requests per minute');

      await user.clear(rateInput);
      await user.type(rateInput, '120');
      await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

      expect(await within(dialog).findByText('Could not update tenant')).toBeInTheDocument();
      expect(within(dialog).getByText(`HTTP ${status}`)).toBeInTheDocument();
      expect(within(dialog).getByText(message)).toBeInTheDocument();
      expect(within(dialog).getByText(code)).toBeInTheDocument();
      expect(within(dialog).getByText(requestId)).toBeInTheDocument();

      expect(patchBodies).toHaveLength(1);
      expect(screen.getByRole('dialog', { name: 'Edit tenant' })).toBeInTheDocument();
      expect(within(dialog).getByLabelText('Requests per minute')).toHaveValue(120);
      expect(within(dialog).getByRole('button', { name: 'Save changes' })).toBeEnabled();
    },
  );

  it('focuses the tenant name field and returns focus on Escape', async () => {
    installAccessMock();
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const table = await screen.findByRole('table', { name: 'Tenants' });
    const editButton = within(table).getByRole('button', { name: 'Edit limits for Acme' });

    await user.click(editButton);
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    const nameInput = within(dialog).getByLabelText('Tenant name');

    await waitFor(() => {
      expect(document.activeElement).toBe(nameInput);
    });

    await user.keyboard('{Escape}');

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(editButton);
    });
  });

  it('keeps the edit dialog open and ignores Escape while saving', async () => {
    let resolvePatch: (response: Response) => void = () => {};
    const pendingPatch = new Promise<Response>((resolve) => {
      resolvePatch = resolve;
    });
    installFetchMock({
      '/api/v1/tenants': (url) => pageResponse(TENANTS, url),
      'PATCH /api/v1/tenants/:id': () => pendingPatch,
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    const rateInput = within(dialog).getByLabelText('Requests per minute');
    const save = within(dialog).getByRole('button', { name: 'Save changes' });
    const close = within(dialog).getByRole('button', { name: 'Close edit tenant dialog' });
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });

    await user.clear(rateInput);
    await user.type(rateInput, '120');
    await user.click(save);

    await waitFor(() => {
      expect(save).toBeDisabled();
    });
    expect(close).toBeDisabled();
    expect(cancel).toBeDisabled();

    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog', { name: 'Edit tenant' })).toBeInTheDocument();

    await act(async () => {
      resolvePatch(jsonResponse({ ...ACME, requests_per_minute: 120 }));
    });

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('wraps focus inside the edit dialog with Tab and Shift+Tab', async () => {
    installAccessMock();
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    const close = within(dialog).getByRole('button', { name: 'Close edit tenant dialog' });
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });

    cancel.focus();
    await user.keyboard('{Tab}');
    expect(document.activeElement).toBe(close);

    close.focus();
    await user.keyboard('{Shift>}{Tab}{/Shift}');
    expect(document.activeElement).toBe(cancel);
  });

  it('locks body scrolling while the edit dialog is open and restores the previous value', async () => {
    document.body.style.overflow = 'scroll';
    installAccessMock();
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    await screen.findByRole('dialog', { name: 'Edit tenant' });
    expect(document.body.style.overflow).toBe('hidden');

    await user.keyboard('{Escape}');

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(document.body.style.overflow).toBe('scroll');
  });

  it('renames a tenant and sends only the name', async () => {
    const { patchBodies } = installEditableTenants(TENANTS);
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    const nameInput = within(dialog).getByLabelText('Tenant name');
    expect(nameInput).toHaveValue('Acme');

    await user.clear(nameInput);
    await user.type(nameInput, '  Acme Labs  ');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([{ name: 'Acme Labs' }]);
    expect(await within(region).findByText('Tenant renamed to Acme Labs.')).toBeInTheDocument();
    await waitFor(() => {
      const updatedTable = within(region).getByRole('table', { name: 'Tenants' });
      expect(within(updatedTable).getByRole('row', { name: /Acme Labs/ })).toBeInTheDocument();
    });
  });

  it('blocks an empty or overlong tenant name before sending', async () => {
    const { patchBodies } = installEditableTenants(TENANTS);
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    const nameInput = within(dialog).getByLabelText('Tenant name');
    const save = within(dialog).getByRole('button', { name: 'Save changes' });

    await user.clear(nameInput);
    await user.click(save);
    expect(await within(dialog).findByText('Enter a tenant name.')).toBeInTheDocument();

    await user.type(nameInput, 'x'.repeat(101));
    await user.click(save);
    expect(within(dialog).getByText('Use 100 characters or fewer.')).toBeInTheDocument();

    expect(patchBodies).toHaveLength(0);
    expect(screen.getByRole('dialog', { name: 'Edit tenant' })).toBeInTheDocument();
  });

  it('keeps the dialog open and shows the duplicate code on a rename conflict', async () => {
    const { patchBodies } = installEditableTenants(TENANTS, () =>
      jsonResponse(
        {
          error: {
            message: "Tenant 'Solo' already exists",
            type: 'invalid_request_error',
            param: 'name',
            code: 'duplicate_tenant',
            request_id: 'req_duplicate_tenant',
          },
        },
        409,
        { 'x-request-id': 'req_duplicate_tenant' },
      ),
    );
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    const nameInput = within(dialog).getByLabelText('Tenant name');

    await user.clear(nameInput);
    await user.type(nameInput, 'Solo');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    expect(await within(dialog).findByText('Could not update tenant')).toBeInTheDocument();
    expect(within(dialog).getByText('HTTP 409')).toBeInTheDocument();
    expect(within(dialog).getByText('duplicate_tenant')).toBeInTheDocument();
    expect(within(dialog).getByText("Tenant 'Solo' already exists")).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Tenant name')).toHaveValue('Solo');
    expect(patchBodies).toEqual([{ name: 'Solo' }]);
    expect(screen.getByRole('dialog', { name: 'Edit tenant' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Save changes' })).toBeEnabled();
  });

  it('deletes a tenant after explicit confirmation and refreshes the list', async () => {
    let tenants = TENANTS.map((tenant) => ({ ...tenant }));
    const deleteRequests: Array<{ id: string; csrf: string | null }> = [];
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => pageResponse(tenants, url),
      'DELETE /api/v1/tenants/:id': (url, init) => {
        const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
        deleteRequests.push({ id, csrf: new Headers(init.headers).get('x-csrf-token') });
        tenants = tenants.filter((tenant) => tenant.id !== id);
        return new Response(null, { status: 204 });
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete tenant' }));

    expect(within(dialog).getByText(/全部 API Key 立即失效/)).toBeInTheDocument();
    expect(within(dialog).getByText(/用量与审计历史仍会保留/)).toBeInTheDocument();
    expect(within(dialog).getByText(/无法在控制台中撤销/)).toBeInTheDocument();

    const listCallsBefore = tenantGetCalls(fetchMock).length;
    await user.click(within(dialog).getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(deleteRequests).toEqual([{ id: ACME.id, csrf: readTestCsrfToken() }]);
    expect(await within(region).findByText('Tenant deleted.')).toBeInTheDocument();

    await waitFor(() => {
      expect(tenantGetCalls(fetchMock).length).toBeGreaterThan(listCallsBefore);
    });
    await waitFor(() => {
      expect(within(region).queryByText('Acme')).not.toBeInTheDocument();
    });
    const updatedTable = within(region).getByRole('table', { name: 'Tenants' });
    expect(within(updatedTable).getByRole('row', { name: /Solo/ })).toBeInTheDocument();
  });

  it('moves back one page when deleting the only tenant on a later page', async () => {
    let tenants: TenantSummary[] = Array.from({ length: 21 }, (_, index) => ({
      id: `${String(index + 1).padStart(8, '0')}-1111-4111-8111-111111111111`,
      name: `Tenant ${index + 1}`,
      created_at: '2026-09-01T00:00:00Z',
      monthly_token_quota: null,
      plan_tokens: null,
      plan_allow_overage: false,
      monthly_cost_budget: null,
      requests_per_minute: null,
      audit_enabled: false,
      model_access_mode: 'all',
    }));
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => pageResponse(tenants, url),
      'DELETE /api/v1/tenants/:id': (url) => {
        const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
        tenants = tenants.filter((tenant) => tenant.id !== id);
        return new Response(null, { status: 204 });
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    expect(await within(region).findByText('Showing 1–20 of 21')).toBeInTheDocument();

    await user.click(within(region).getByRole('button', { name: 'Next tenant page' }));
    expect(await within(region).findByText('Showing 21–21 of 21')).toBeInTheDocument();
    const table = await screen.findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Tenant 21' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete tenant' }));

    const pageCallsBeforeDelete = accessPageCalls(fetchMock).length;
    await user.click(within(dialog).getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(await within(region).findByText('Showing 1–20 of 20')).toBeInTheDocument();
    expect(within(region).queryByText('Tenant 21')).not.toBeInTheDocument();
    expect(within(region).queryByText('No tenants yet')).not.toBeInTheDocument();

    await waitFor(() => {
      const offsets = accessPageCalls(fetchMock)
        .slice(pageCallsBeforeDelete)
        .map(([input]) => toUrl(input).searchParams.get('offset') ?? '');
      expect(offsets).toContain('0');
    });
  });

  it('keeps the current page when other tenants remain after a delete', async () => {
    let tenants: TenantSummary[] = Array.from({ length: 41 }, (_, index) => ({
      id: `${String(index + 1).padStart(8, '0')}-1111-4111-8111-111111111111`,
      name: `Tenant ${index + 1}`,
      created_at: '2026-09-01T00:00:00Z',
      monthly_token_quota: null,
      plan_tokens: null,
      plan_allow_overage: false,
      monthly_cost_budget: null,
      requests_per_minute: null,
      audit_enabled: false,
      model_access_mode: 'all',
    }));
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => pageResponse(tenants, url),
      'DELETE /api/v1/tenants/:id': (url) => {
        const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
        tenants = tenants.filter((tenant) => tenant.id !== id);
        return new Response(null, { status: 204 });
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    await within(region).findByText('Showing 1–20 of 41');
    await user.click(within(region).getByRole('button', { name: 'Next tenant page' }));
    expect(await within(region).findByText('Showing 21–40 of 41')).toBeInTheDocument();

    const table = await screen.findByRole('table', { name: 'Tenants' });
    await user.click(within(table).getByRole('button', { name: 'Edit limits for Tenant 21' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete tenant' }));

    const pageCallsBeforeDelete = accessPageCalls(fetchMock).length;
    await user.click(within(dialog).getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(await within(region).findByText('Showing 21–40 of 40')).toBeInTheDocument();
    expect(within(region).queryByText('Tenant 21')).not.toBeInTheDocument();
    const updatedTable = within(region).getByRole('table', { name: 'Tenants' });
    expect(within(updatedTable).getByText('Tenant 22')).toBeInTheDocument();

    const offsetsAfterDelete = accessPageCalls(fetchMock)
      .slice(pageCallsBeforeDelete)
      .map(([input]) => toUrl(input).searchParams.get('offset') ?? '');
    expect(offsetsAfterDelete).not.toContain('0');
  });

  it('shows the normal empty state when deleting the only tenant on the first page', async () => {
    let tenants = [{ ...ACME }];
    installFetchMock({
      '/api/v1/tenants': (url) => pageResponse(tenants, url),
      'DELETE /api/v1/tenants/:id': (url) => {
        const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
        tenants = tenants.filter((tenant) => tenant.id !== id);
        return new Response(null, { status: 204 });
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const region = tenantRegion();
    const table = await screen.findByRole('table', { name: 'Tenants' });
    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete tenant' }));
    await user.click(within(dialog).getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(await within(region).findByText('No tenants yet')).toBeInTheDocument();
  });

  it('resets the API key tenant filter when its tenant is deleted', async () => {
    let tenants = TENANTS.map((tenant) => ({ ...tenant }));
    let deleted = false;
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => pageResponse(tenants, url),
      '/api/v1/keys': (url) => {
        const tenantId = url.searchParams.get('tenant_id');
        if (tenantId === ACME.id) {
          if (deleted) {
            return jsonResponse(
              {
                error: {
                  message: 'Tenant was not found',
                  type: 'invalid_request_error',
                  param: 'tenant_id',
                  code: 'tenant_not_found',
                  request_id: 'req_deleted_tenant_keys',
                },
              },
              404,
              { 'x-request-id': 'req_deleted_tenant_keys' },
            );
          }
          return jsonResponse({
            items: [PRODUCTION_KEY],
            total: 1,
            limit: PAGE_SIZE,
            offset: 0,
            tenant_id: ACME.id,
          });
        }
        return jsonResponse({
          items: [PRODUCTION_KEY],
          total: 1,
          limit: PAGE_SIZE,
          offset: 0,
          tenant_id: null,
        });
      },
      'DELETE /api/v1/tenants/:id': (url) => {
        const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
        deleted = true;
        tenants = tenants.filter((tenant) => tenant.id !== id);
        return new Response(null, { status: 204 });
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const keyRegion = screen.getByRole('region', { name: 'API keys' });
    const filter = within(keyRegion).getByLabelText('Tenant filter');
    await within(keyRegion).findByRole('option', { name: 'Acme' });
    await user.selectOptions(filter, ACME.id);
    await waitFor(() => {
      expect(filter).toHaveValue(ACME.id);
      expect(
        keyGetCalls(fetchMock).some(
          ([input]) => toUrl(input).searchParams.get('tenant_id') === ACME.id,
        ),
      ).toBe(true);
    });

    const table = await screen.findByRole('table', { name: 'Tenants' });
    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete tenant' }));

    const keyCallsBeforeDelete = keyGetCalls(fetchMock).length;
    await user.click(within(dialog).getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(within(keyRegion).getByLabelText('Tenant filter')).toHaveValue('');
    });

    await waitFor(() => {
      const callsAfterDelete = keyGetCalls(fetchMock).slice(keyCallsBeforeDelete);
      expect(callsAfterDelete.length).toBeGreaterThan(0);
      expect(
        callsAfterDelete.some(([input]) => toUrl(input).searchParams.get('tenant_id') === ACME.id),
      ).toBe(false);
      expect(
        callsAfterDelete.some(([input]) => toUrl(input).searchParams.get('tenant_id') === null),
      ).toBe(true);
    });
    expect(within(keyRegion).queryByText('Could not load API keys')).not.toBeInTheDocument();
  });

  it('falls back to all tenants when the selected usage tenant is deleted', async () => {
    let tenants = TENANTS.map((tenant) => ({ ...tenant }));
    installFetchMock({
      '/api/v1/tenants': (url) => pageResponse(tenants, url),
      'DELETE /api/v1/tenants/:id': (url) => {
        const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
        tenants = tenants.filter((tenant) => tenant.id !== id);
        return new Response(null, { status: 204 });
      },
    });
    const user = userEvent.setup();
    renderApp();

    await signIn(user);
    await user.click(screen.getByRole('tab', { name: 'Usage' }));
    const tenantSelect = await screen.findByLabelText('Tenant');
    await screen.findByRole('option', { name: 'Acme' });
    await user.selectOptions(tenantSelect, ACME.id);
    expect(tenantSelect).toHaveValue(ACME.id);

    await user.click(screen.getByRole('tab', { name: 'Access' }));
    const table = await screen.findByRole('table', { name: 'Tenants' });
    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete tenant' }));
    await user.click(within(dialog).getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole('tab', { name: 'Usage' }));
    await waitFor(() => {
      expect(screen.getByLabelText('Tenant')).toHaveValue('');
    });
    expect(screen.queryByRole('option', { name: 'Acme' })).not.toBeInTheDocument();
  });
});
