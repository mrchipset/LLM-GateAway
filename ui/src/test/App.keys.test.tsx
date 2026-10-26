import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ApiKeySummary, CreateApiKeyInput, CreatedApiKey, TenantSummary } from '../api/client';
import { connectWithKey } from './connectWithKey';
import { installFetchMock, jsonResponse, toUrl, type Routes } from './fetchMock';
import { renderApp } from './renderApp';

const FIXED_NOW = new Date('2026-10-25T12:00:00.000Z');
const PAGE_SIZE = 20;
const CREATED_SECRET = 'lgw_live_created_secret_123';

const ACME: TenantSummary = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Acme',
  created_at: '2026-09-01T00:00:00Z',
  monthly_token_quota: 1_000_000,
  requests_per_minute: 60,
};

const SOLO: TenantSummary = {
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Solo',
  created_at: '2026-09-02T00:00:00Z',
  monthly_token_quota: null,
  requests_per_minute: null,
};

const TENANTS = [ACME, SOLO];

const PRODUCTION: ApiKeySummary = {
  id: 'aaaaaaaa-1111-4111-8111-111111111111',
  tenant_id: ACME.id,
  name: 'Production',
  key_prefix: 'lgw_live_prod',
  created_at: '2026-10-01T08:15:00Z',
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
};

const ANALYTICS: ApiKeySummary = {
  id: 'aaaaaaaa-2222-4222-8222-222222222222',
  tenant_id: ACME.id,
  name: 'Analytics',
  key_prefix: 'lgw_live_anal',
  created_at: '2026-10-02T09:30:00Z',
  expires_at: '2026-12-01T10:00:00Z',
  revoked_at: null,
  last_used_at: '2026-10-24T09:30:00Z',
};

const OLD_STAGING: ApiKeySummary = {
  id: 'aaaaaaaa-3333-4333-8333-333333333333',
  tenant_id: SOLO.id,
  name: 'Old staging',
  key_prefix: 'lgw_test_old',
  created_at: '2026-09-10T11:45:00Z',
  expires_at: null,
  revoked_at: '2026-10-20T00:00:00Z',
  last_used_at: null,
};

const LEGACY: ApiKeySummary = {
  id: 'aaaaaaaa-4444-4444-8444-444444444444',
  tenant_id: '99999999-9999-4999-8999-999999999999',
  name: 'Legacy',
  key_prefix: 'lgw_test_legacy',
  created_at: '2026-09-05T07:20:00Z',
  expires_at: '2026-10-20T00:00:00Z',
  revoked_at: null,
  last_used_at: null,
};

const KEYS = [PRODUCTION, ANALYTICS, OLD_STAGING, LEGACY];

const EXPIRING: ApiKeySummary = {
  ...PRODUCTION,
  id: 'aaaaaaaa-5555-4555-8555-555555555555',
  name: 'Expiring',
  key_prefix: 'lgw_live_exp',
  expires_at: '2026-10-25T12:01:00Z',
};

const REVOKED_EXPIRED: ApiKeySummary = {
  ...LEGACY,
  id: 'aaaaaaaa-6666-4666-8666-666666666666',
  name: 'Revoked and expired',
  key_prefix: 'lgw_test_both',
  revoked_at: '2026-10-20T00:00:00Z',
};

const MANY_KEYS: ApiKeySummary[] = Array.from({ length: 45 }, (_, index) => ({
  id: `key-${String(index + 1).padStart(4, '0')}`,
  tenant_id: ACME.id,
  name: `Key ${String(index + 1).padStart(2, '0')}`,
  key_prefix: `lgw_bulk_${String(index + 1).padStart(2, '0')}`,
  created_at: '2026-10-01T00:00:00Z',
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
}));

function createdKey(overrides: Partial<CreatedApiKey> = {}): CreatedApiKey {
  return {
    id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    tenant_id: ACME.id,
    name: 'Nightly',
    key: CREATED_SECRET,
    key_prefix: 'lgw_live_created',
    created_at: '2026-10-25T12:00:00Z',
    expires_at: null,
    ...overrides,
  };
}

function summaryFromCreated(created: CreatedApiKey): ApiKeySummary {
  return {
    id: created.id,
    tenant_id: created.tenant_id,
    name: created.name,
    key_prefix: created.key_prefix,
    created_at: created.created_at,
    expires_at: created.expires_at,
    revoked_at: null,
    last_used_at: null,
  };
}

function tenantPageResponse(tenants: TenantSummary[], url: URL): Response {
  const limit = Number(url.searchParams.get('limit') ?? '100');
  const offset = Number(url.searchParams.get('offset') ?? '0');
  return jsonResponse({
    items: tenants.slice(offset, offset + limit),
    total: tenants.length,
    limit,
    offset,
  });
}

function keysPageResponse(keys: ApiKeySummary[], url: URL): Response {
  const limit = Number(url.searchParams.get('limit') ?? String(PAGE_SIZE));
  const offset = Number(url.searchParams.get('offset') ?? '0');
  const tenantId = url.searchParams.get('tenant_id');
  const filtered = tenantId === null ? keys : keys.filter((key) => key.tenant_id === tenantId);
  return jsonResponse({
    items: filtered.slice(offset, offset + limit),
    total: filtered.length,
    limit,
    offset,
    tenant_id: tenantId,
  });
}

function apiError(status: number, code: string, message: string, requestId: string): Response {
  return jsonResponse(
    {
      error: {
        message,
        type: 'invalid_request_error',
        param: null,
        code,
        request_id: requestId,
      },
    },
    status,
    { 'x-request-id': requestId },
  );
}

function installKeyStore(initial: ApiKeySummary[], overrides: Routes = {}) {
  let keys = initial.map((key) => ({ ...key }));
  const createBodies: CreateApiKeyInput[] = [];
  const deleteCalls: string[] = [];

  const fetchMock = installFetchMock({
    '/api/v1/tenants': (url) => tenantPageResponse(TENANTS, url),
    '/api/v1/keys': (url) => keysPageResponse(keys, url),
    'POST /api/v1/keys': (_url, init) => {
      const body = JSON.parse(String(init.body)) as CreateApiKeyInput;
      createBodies.push(body);
      const created = createdKey({
        tenant_id: body.tenant_id,
        name: body.name,
        expires_at: body.expires_at ?? null,
      });
      keys = [summaryFromCreated(created), ...keys];
      return jsonResponse(created, 201);
    },
    'DELETE /api/v1/keys/:id': (url) => {
      const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
      deleteCalls.push(id);
      const existing = keys.find((key) => key.id === id);
      if (existing === undefined || existing.revoked_at !== null) {
        return apiError(
          404,
          'key_not_found',
          'API key not found or already revoked',
          'req_key_404',
        );
      }
      keys = keys.map((key) =>
        key.id === id ? { ...key, revoked_at: FIXED_NOW.toISOString() } : key,
      );
      return new Response(null, { status: 204 });
    },
    ...overrides,
  });

  return { fetchMock, createBodies, deleteCalls };
}

function keyGetCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return url.pathname === '/api/v1/keys' && (init?.method ?? 'GET').toUpperCase() === 'GET';
  });
}

function createKeyCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return url.pathname === '/api/v1/keys' && init?.method?.toUpperCase() === 'POST';
  });
}

function deleteKeyCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return url.pathname.startsWith('/api/v1/keys/') && init?.method?.toUpperCase() === 'DELETE';
  });
}

function keysRegion() {
  return screen.getByRole('region', { name: 'API keys' });
}

async function openAccessKeys(user: ReturnType<typeof userEvent.setup>) {
  await connectWithKey(user);
  await user.click(await screen.findByRole('tab', { name: 'Access' }));
  await screen.findByRole('heading', { name: 'API keys' });
}

async function openCreateDialog(user: ReturnType<typeof userEvent.setup>) {
  const region = keysRegion();
  const open = within(region).getByRole('button', { name: 'Create API key' });
  await waitFor(() => {
    expect(open).toBeEnabled();
  });
  await user.click(open);
  return screen.findByRole('dialog', { name: 'Create API key' });
}

async function fillCreateForm(
  user: ReturnType<typeof userEvent.setup>,
  dialog: HTMLElement,
  options: { tenantId?: string; name?: string; expiry?: string } = {},
) {
  if (options.tenantId !== undefined) {
    await user.selectOptions(within(dialog).getByLabelText('Tenant'), options.tenantId);
  }
  if (options.name !== undefined) {
    await user.type(within(dialog).getByLabelText('Key name'), options.name);
  }
  if (options.expiry !== undefined) {
    fireEvent.change(within(dialog).getByLabelText('Expires at (optional)'), {
      target: { value: options.expiry },
    });
  }
}

async function createKeyThroughDialog(user: ReturnType<typeof userEvent.setup>) {
  const dialog = await openCreateDialog(user);
  await fillCreateForm(user, dialog, { tenantId: ACME.id, name: 'Nightly' });
  await user.click(within(dialog).getByRole('button', { name: 'Create key' }));
  return screen.findByRole('dialog', { name: 'API key created' });
}

describe('API key management', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(FIXED_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.style.overflow = '';
    Reflect.deleteProperty(navigator, 'clipboard');
  });

  it('does not request API keys before connecting and shows the connect prompt', async () => {
    const fetchMock = installFetchMock();
    const user = userEvent.setup();
    renderApp();

    await user.click(screen.getByRole('tab', { name: 'Access' }));

    expect(await screen.findByText('Connect a master key to manage API keys.')).toBeInTheDocument();
    expect(keyGetCalls(fetchMock)).toHaveLength(0);
  });

  it('renders key rows with prefixes, tenant names, UTC times, statuses, and actions', async () => {
    installKeyStore(KEYS);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const region = keysRegion();
    expect(await within(region).findByText('4 keys')).toBeInTheDocument();

    const table = await screen.findByRole('table', { name: 'API keys' });
    for (const label of [
      'Name',
      'Prefix',
      'Tenant',
      'Created (UTC)',
      'Expires (UTC)',
      'Status',
      'Last used (UTC)',
      'Action',
    ]) {
      expect(within(table).getByRole('columnheader', { name: label })).toBeInTheDocument();
    }

    expect(within(table).getByText('Production')).toBeInTheDocument();
    expect(within(table).getByText('lgw_live_prod')).toBeInTheDocument();
    expect(within(table).getByText('Oct 01, 2026, 08:15 UTC')).toBeInTheDocument();
    expect(within(table).getByText('Dec 01, 2026, 10:00 UTC')).toBeInTheDocument();
    expect(within(table).getByText('Oct 24, 2026, 09:30 UTC')).toBeInTheDocument();
    expect(within(table).getByText('lgw_test_legacy')).toBeInTheDocument();

    await waitFor(() => {
      expect(within(table).getAllByText('Acme')).toHaveLength(2);
    });
    expect(within(table).getByText('Solo')).toBeInTheDocument();
    expect(within(table).getByText('99999999…')).toBeInTheDocument();

    expect(within(table).getAllByText('Active')).toHaveLength(2);
    expect(within(table).getByText('Revoked')).toBeInTheDocument();
    expect(within(table).getByText('Expired')).toBeInTheDocument();

    const productionRow = within(table).getByRole('row', { name: /Production/ });
    expect(within(productionRow).getAllByText('—')).toHaveLength(2);

    expect(within(table).getAllByRole('button', { name: /^Revoke / })).toHaveLength(3);
    const revokedRow = within(table).getByRole('row', { name: /Old staging/ });
    expect(within(revokedRow).queryByRole('button', { name: /^Revoke / })).not.toBeInTheDocument();
  });

  it('advances an expiring key to Expired while the page stays open', async () => {
    vi.useRealTimers();
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] });
    vi.setSystemTime(FIXED_NOW);
    installKeyStore([EXPIRING]);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const table = await screen.findByRole('table', { name: 'API keys' });
    const row = within(table).getByRole('row', { name: /Expiring/ });
    expect(within(row).getByText('Active')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(60_000);
    });

    await waitFor(() => {
      expect(within(row).getByText('Expired')).toBeInTheDocument();
    });
  });

  it('prefers Revoked over Expired when a key is both revoked and past expiry', async () => {
    installKeyStore([REVOKED_EXPIRED]);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const table = await screen.findByRole('table', { name: 'API keys' });
    const row = within(table).getByRole('row', { name: /Revoked and expired/ });

    expect(within(row).getByText('Revoked')).toBeInTheDocument();
    expect(within(row).queryByText('Expired')).not.toBeInTheDocument();
  });

  it('loads key rows through a loading skeleton', async () => {
    let resolvePage: (response: Response) => void = () => {};
    const pendingPage = new Promise<Response>((resolve) => {
      resolvePage = resolve;
    });
    installKeyStore([], { '/api/v1/keys': () => pendingPage });
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const region = keysRegion();
    expect(await within(region).findByText('Loading API keys…')).toBeInTheDocument();

    await act(async () => {
      resolvePage(
        jsonResponse({ items: KEYS, total: KEYS.length, limit: 20, offset: 0, tenant_id: null }),
      );
    });

    expect(await screen.findByRole('table', { name: 'API keys' })).toBeInTheDocument();
  });

  it('filters by tenant with tenant_id and defaults the create tenant to the filter', async () => {
    const { fetchMock } = installKeyStore(KEYS);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const region = keysRegion();
    await screen.findByRole('table', { name: 'API keys' });

    const initialCall = keyGetCalls(fetchMock)[0];
    expect(initialCall).toBeDefined();
    if (initialCall !== undefined) {
      const url = toUrl(initialCall[0]);
      expect(url.searchParams.has('tenant_id')).toBe(false);
      expect(url.searchParams.get('limit')).toBe(String(PAGE_SIZE));
      expect(url.searchParams.get('offset')).toBe('0');
    }

    const filter = within(region).getByLabelText('Tenant filter');
    await waitFor(() => {
      expect(filter).toBeEnabled();
    });
    await user.selectOptions(filter, ACME.id);

    await waitFor(() => {
      expect(
        keyGetCalls(fetchMock).some(
          ([input]) => toUrl(input).searchParams.get('tenant_id') === ACME.id,
        ),
      ).toBe(true);
    });

    const filteredTable = await screen.findByRole('table', { name: 'API keys' });
    expect(within(filteredTable).getByText('Production')).toBeInTheDocument();
    expect(within(filteredTable).getByText('Analytics')).toBeInTheDocument();
    expect(within(filteredTable).queryByText('Old staging')).not.toBeInTheDocument();
    expect(await within(region).findByText('2 keys')).toBeInTheDocument();

    await user.click(within(region).getByRole('button', { name: 'Create API key' }));
    const dialog = await screen.findByRole('dialog', { name: 'Create API key' });
    expect(within(dialog).getByLabelText('Tenant')).toHaveValue(ACME.id);
  });

  it('shows a muted truncation note when the tenant query is capped', async () => {
    installKeyStore(KEYS, {
      '/api/v1/tenants': (url) => {
        const limit = Number(url.searchParams.get('limit') ?? '100');
        return jsonResponse({ items: TENANTS, total: 150, limit, offset: 0 });
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const region = keysRegion();
    const filter = within(region).getByLabelText('Tenant filter');
    const note = await within(region).findByText(
      'Showing the first 100 of 150 tenants; use the API for the rest.',
    );

    expect(filter.getAttribute('aria-describedby')).toBe(note.id);
    expect(note).toHaveClass('text-ink-muted');
  });

  it('paginates key pages with limit 20 and the right offsets', async () => {
    const { fetchMock } = installKeyStore(MANY_KEYS);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const region = keysRegion();
    expect(await within(region).findByText('45 keys')).toBeInTheDocument();

    let table = await screen.findByRole('table', { name: 'API keys' });
    expect(within(table).getAllByRole('rowheader')).toHaveLength(20);
    expect(within(region).getByText('Showing 1–20 of 45')).toBeInTheDocument();
    expect(within(region).getByRole('button', { name: 'Previous key page' })).toBeDisabled();
    expect(within(region).getByRole('button', { name: 'Next key page' })).toBeEnabled();

    await user.click(within(region).getByRole('button', { name: 'Next key page' }));
    expect(await within(region).findByText('Showing 21–40 of 45')).toBeInTheDocument();
    table = await screen.findByRole('table', { name: 'API keys' });
    expect(within(table).getAllByRole('rowheader')).toHaveLength(20);
    expect(within(table).getByText('Key 21')).toBeInTheDocument();

    await user.click(within(region).getByRole('button', { name: 'Next key page' }));
    expect(await within(region).findByText('Showing 41–45 of 45')).toBeInTheDocument();
    table = await screen.findByRole('table', { name: 'API keys' });
    expect(within(table).getAllByRole('rowheader')).toHaveLength(5);
    expect(within(table).getByText('Key 45')).toBeInTheDocument();
    expect(within(region).getByRole('button', { name: 'Next key page' })).toBeDisabled();

    const offsets = keyGetCalls(fetchMock).map(
      ([input]) => toUrl(input).searchParams.get('offset') ?? '',
    );
    expect(offsets).toEqual(['0', '20', '40']);
    for (const call of keyGetCalls(fetchMock)) {
      expect(toUrl(call[0]).searchParams.get('limit')).toBe(String(PAGE_SIZE));
    }
  });

  it('shows an empty state with a create call to action', async () => {
    installKeyStore([]);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const region = keysRegion();
    expect(await within(region).findByText('0 keys')).toBeInTheDocument();
    expect(within(region).getByText('No API keys')).toBeInTheDocument();

    await user.click(within(region).getByRole('button', { name: 'Create your first API key' }));
    expect(await screen.findByRole('dialog', { name: 'Create API key' })).toBeInTheDocument();
  });

  it('disables key creation and asks for a tenant when there are no tenants', async () => {
    installKeyStore([], {
      '/api/v1/tenants': (url) => tenantPageResponse([], url),
    });
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const region = keysRegion();

    expect(await within(region).findByText('Create a tenant first.')).toBeInTheDocument();
    expect(within(region).getByRole('button', { name: 'Create API key' })).toBeDisabled();
    expect(
      within(region).getByRole('button', { name: 'Create your first API key' }),
    ).toBeDisabled();
  });

  it('shows the HTTP status, message, code, and request id when key loading fails', async () => {
    let keyRequests = 0;
    installKeyStore([], {
      '/api/v1/keys': () => {
        keyRequests += 1;
        return apiError(500, 'key_store_unavailable', 'Key store unavailable', 'req_keys_500');
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const region = keysRegion();

    expect(await within(region).findByText('Could not load API keys')).toBeInTheDocument();
    expect(within(region).getByText('HTTP 500')).toBeInTheDocument();
    expect(within(region).getByText('Key store unavailable')).toBeInTheDocument();
    expect(within(region).getByText('key_store_unavailable')).toBeInTheDocument();
    expect(within(region).getByText('req_keys_500')).toBeInTheDocument();

    const before = keyRequests;
    await user.click(within(region).getByRole('button', { name: 'Retry loading API keys' }));
    await waitFor(() => {
      expect(keyRequests).toBeGreaterThan(before);
    });
  });

  it('refreshes the key page and shows a UTC last-updated time', async () => {
    const { fetchMock } = installKeyStore(KEYS);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    await screen.findByRole('table', { name: 'API keys' });

    const region = keysRegion();
    expect(await within(region).findByText('Updated 12:00:00 UTC')).toBeInTheDocument();

    const before = keyGetCalls(fetchMock).length;
    await user.click(within(region).getByRole('button', { name: 'Refresh API keys' }));

    await waitFor(() => {
      expect(keyGetCalls(fetchMock).length).toBeGreaterThan(before);
    });
  });

  it('validates the tenant, name, length, and expiry before sending', async () => {
    const { fetchMock } = installKeyStore(KEYS);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const dialog = await openCreateDialog(user);
    const submit = within(dialog).getByRole('button', { name: 'Create key' });

    await user.click(submit);
    expect(await within(dialog).findByText('Select a tenant.')).toBeInTheDocument();
    expect(within(dialog).getByText('Enter a key name.')).toBeInTheDocument();
    expect(createKeyCalls(fetchMock)).toHaveLength(0);

    await fillCreateForm(user, dialog, { tenantId: ACME.id, name: '   ' });
    await user.click(submit);
    expect(within(dialog).getByText('Enter a key name.')).toBeInTheDocument();

    const nameInput = within(dialog).getByLabelText('Key name');
    await user.clear(nameInput);
    await user.type(nameInput, 'a'.repeat(101));
    await user.click(submit);
    expect(within(dialog).getByText('Use 100 characters or fewer.')).toBeInTheDocument();

    await user.clear(nameInput);
    await fillCreateForm(user, dialog, { name: 'Nightly', expiry: '2026-10-24T10:00' });
    await user.click(submit);
    expect(await within(dialog).findByText('Enter an expiry in the future.')).toBeInTheDocument();

    expect(createKeyCalls(fetchMock)).toHaveLength(0);
    expect(screen.getByRole('dialog', { name: 'Create API key' })).toBeInTheDocument();
  });

  it('sends a trimmed name, tenant, ISO UTC expiry, and omits a blank expiry', async () => {
    const { fetchMock, createBodies } = installKeyStore(KEYS);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const dialog = await openCreateDialog(user);
    const localExpiry = '2026-12-31T23:30';
    await fillCreateForm(user, dialog, {
      tenantId: ACME.id,
      name: '  Nightly  ',
      expiry: localExpiry,
    });
    await user.click(within(dialog).getByRole('button', { name: 'Create key' }));

    const secretDialog = await screen.findByRole('dialog', { name: 'API key created' });
    expect(within(secretDialog).getByText(CREATED_SECRET)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Create API key' })).not.toBeInTheDocument();
    });

    expect(createBodies).toHaveLength(1);
    expect(createBodies[0]).toEqual({
      name: 'Nightly',
      tenant_id: ACME.id,
      expires_at: new Date(localExpiry).toISOString(),
    });
    expect(Object.keys(createBodies[0] ?? {}).sort()).toEqual(['expires_at', 'name', 'tenant_id']);

    const createCall = createKeyCalls(fetchMock)[0];
    expect(new Headers(createCall?.[1]?.headers).get('Authorization')).toBe('Bearer mk_test_123');

    await user.click(within(secretDialog).getByRole('button', { name: 'Close' }));
    await user.click(within(secretDialog).getByRole('button', { name: 'Close without copying' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'API key created' })).not.toBeInTheDocument();
    });

    await waitFor(() => {
      const refreshedTable = within(keysRegion()).getByRole('table', { name: 'API keys' });
      expect(within(refreshedTable).getByText('Nightly')).toBeInTheDocument();
    });

    const secondDialog = await openCreateDialog(user);
    await fillCreateForm(user, secondDialog, { tenantId: SOLO.id, name: 'No expiry' });
    await user.click(within(secondDialog).getByRole('button', { name: 'Create key' }));

    await waitFor(() => {
      expect(createBodies).toHaveLength(2);
    });
    expect(createBodies[1]).toEqual({ name: 'No expiry', tenant_id: SOLO.id });
  });

  it('disables every close path while a key create request is pending', async () => {
    let resolveCreate: (response: Response) => void = () => {};
    const pendingCreate = new Promise<Response>((resolve) => {
      resolveCreate = resolve;
    });
    installKeyStore(KEYS, { 'POST /api/v1/keys': () => pendingCreate });
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const dialog = await openCreateDialog(user);
    await fillCreateForm(user, dialog, { tenantId: ACME.id, name: 'Nightly' });
    await user.click(within(dialog).getByRole('button', { name: 'Create key' }));

    const close = within(dialog).getByRole('button', { name: 'Close create key dialog' });
    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    const submit = within(dialog).getByRole('button', { name: 'Creating…' });
    await waitFor(() => {
      expect(submit).toBeDisabled();
    });
    expect(close).toBeDisabled();
    expect(cancel).toBeDisabled();
    expect(within(dialog).getByLabelText('Tenant')).toBeDisabled();
    expect(within(dialog).getByLabelText('Key name')).toBeDisabled();
    expect(within(dialog).getByLabelText('Expires at (optional)')).toBeDisabled();

    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog', { name: 'Create API key' })).toBeInTheDocument();

    await act(async () => {
      resolveCreate(jsonResponse(createdKey(), 201));
    });

    expect(await screen.findByRole('dialog', { name: 'API key created' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Create API key' })).not.toBeInTheDocument();
    });
  });

  it.each([
    {
      status: 400,
      code: 'invalid_request_body',
      message: 'expires_at must be in the future',
      requestId: 'req_create_400',
    },
    {
      status: 404,
      code: 'tenant_not_found',
      message: `Tenant '${ACME.id}' was not found`,
      requestId: 'req_create_404',
    },
  ])(
    'keeps the create dialog open on a $status API key error',
    async ({ status, code, message, requestId }) => {
      const { fetchMock } = installKeyStore(KEYS, {
        'POST /api/v1/keys': () => apiError(status, code, message, requestId),
      });
      const user = userEvent.setup();
      renderApp();

      await openAccessKeys(user);
      const dialog = await openCreateDialog(user);
      await fillCreateForm(user, dialog, { tenantId: ACME.id, name: 'Nightly' });
      await user.click(within(dialog).getByRole('button', { name: 'Create key' }));

      expect(await within(dialog).findByText('Could not create API key')).toBeInTheDocument();
      expect(within(dialog).getByText(`HTTP ${status}`)).toBeInTheDocument();
      expect(within(dialog).getByText(message)).toBeInTheDocument();
      expect(within(dialog).getByText(code)).toBeInTheDocument();
      expect(within(dialog).getByText(requestId)).toBeInTheDocument();
      expect(within(dialog).getByLabelText('Key name')).toHaveValue('Nightly');
      expect(createKeyCalls(fetchMock)).toHaveLength(1);

      await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
      await waitFor(() => {
        expect(screen.queryByRole('dialog', { name: 'Create API key' })).not.toBeInTheDocument();
      });

      const reopened = await openCreateDialog(user);
      expect(within(reopened).queryByText('Could not create API key')).not.toBeInTheDocument();
      await fillCreateForm(user, reopened, { tenantId: ACME.id, name: 'Nightly' });
      await user.click(within(reopened).getByRole('button', { name: 'Create key' }));
      expect(await within(reopened).findByText('Could not create API key')).toBeInTheDocument();

      await user.type(within(reopened).getByLabelText('Key name'), 'x');
      await waitFor(() => {
        expect(within(reopened).queryByText('Could not create API key')).not.toBeInTheDocument();
      });
      expect(createKeyCalls(fetchMock)).toHaveLength(2);
    },
  );

  it('asks for confirmation before closing an uncopied key with Escape', async () => {
    installKeyStore(KEYS);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const secretDialog = await createKeyThroughDialog(user);
    expect(within(secretDialog).getByText(CREATED_SECRET)).toBeInTheDocument();

    await user.keyboard('{Escape}');

    expect(
      await within(secretDialog).findByText('You have not copied this key. Close anyway?'),
    ).toBeInTheDocument();
    expect(within(secretDialog).getByText(CREATED_SECRET)).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'API key created' })).toBeInTheDocument();

    const keepKey = within(secretDialog).getByRole('button', { name: 'Keep key' });
    await waitFor(() => {
      expect(document.activeElement).toBe(keepKey);
    });
  });

  it('restores the key dialog when Keep key is chosen', async () => {
    installKeyStore(KEYS);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const secretDialog = await createKeyThroughDialog(user);

    await user.click(within(secretDialog).getByRole('button', { name: 'Close' }));
    expect(
      await within(secretDialog).findByText('You have not copied this key. Close anyway?'),
    ).toBeInTheDocument();

    await user.click(within(secretDialog).getByRole('button', { name: 'Keep key' }));

    expect(
      within(secretDialog).queryByText('You have not copied this key. Close anyway?'),
    ).not.toBeInTheDocument();
    expect(within(secretDialog).getByText(CREATED_SECRET)).toBeInTheDocument();
    expect(within(secretDialog).getByRole('button', { name: 'Close' })).toBeInTheDocument();

    const copy = within(secretDialog).getByRole('button', { name: 'Copy key' });
    await waitFor(() => {
      expect(document.activeElement).toBe(copy);
    });
  });

  it('closes without copying only after confirmation and removes the secret', async () => {
    installKeyStore(KEYS);
    const { queryClient } = renderApp();
    const user = userEvent.setup();

    await openAccessKeys(user);
    const secretDialog = await createKeyThroughDialog(user);

    await user.click(within(secretDialog).getByRole('button', { name: 'Close API key dialog' }));
    expect(
      await within(secretDialog).findByText('You have not copied this key. Close anyway?'),
    ).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'API key created' })).toBeInTheDocument();

    await user.click(within(secretDialog).getByRole('button', { name: 'Close without copying' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'API key created' })).not.toBeInTheDocument();
    });
    expect(screen.queryByText(CREATED_SECRET)).not.toBeInTheDocument();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe('');

    const mutationCacheText = JSON.stringify(
      queryClient
        .getMutationCache()
        .getAll()
        .map((mutation) => mutation.state),
    );
    expect(mutationCacheText).not.toContain(CREATED_SECRET);
  });

  it('closes a copied key immediately on Escape', async () => {
    installKeyStore(KEYS);
    const user = userEvent.setup();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    renderApp();

    await openAccessKeys(user);
    const secretDialog = await createKeyThroughDialog(user);

    await user.click(within(secretDialog).getByRole('button', { name: 'Copy key' }));
    expect(await within(secretDialog).findByText('Copied to clipboard.')).toBeInTheDocument();

    await user.keyboard('{Escape}');

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'API key created' })).not.toBeInTheDocument();
    });
    expect(screen.queryByText(CREATED_SECRET)).not.toBeInTheDocument();
    expect(
      screen.queryByText('You have not copied this key. Close anyway?'),
    ).not.toBeInTheDocument();
  });

  it('shows the key once, copies it, clears it on close, and never stores it', async () => {
    installKeyStore(KEYS);
    const { queryClient } = renderApp();
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    await openAccessKeys(user);
    const secretDialog = await createKeyThroughDialog(user);

    expect(within(secretDialog).getByText(CREATED_SECRET)).toBeInTheDocument();
    expect(within(secretDialog).getByText(/shown only once/i)).toBeInTheDocument();

    const openMutationCacheText = JSON.stringify(
      queryClient
        .getMutationCache()
        .getAll()
        .map((mutation) => mutation.state),
    );
    expect(openMutationCacheText).not.toContain(CREATED_SECRET);
    const openQueryCacheText = JSON.stringify(
      queryClient
        .getQueryCache()
        .getAll()
        .map((query) => ({ key: query.queryKey, data: query.state.data })),
    );
    expect(openQueryCacheText).not.toContain(CREATED_SECRET);

    const copy = within(secretDialog).getByRole('button', { name: 'Copy key' });
    await waitFor(() => {
      expect(document.activeElement).toBe(copy);
    });

    await user.click(copy);
    expect(await within(secretDialog).findByText('Copied to clipboard.')).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(CREATED_SECRET);

    await user.click(within(secretDialog).getByRole('button', { name: 'Close' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'API key created' })).not.toBeInTheDocument();
    });
    expect(screen.queryByText(CREATED_SECRET)).not.toBeInTheDocument();

    const createButton = within(keysRegion()).getByRole('button', { name: 'Create API key' });
    await waitFor(() => {
      expect(document.activeElement).toBe(createButton);
    });

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe('');
    expect(window.location.href).not.toContain(CREATED_SECRET);

    const queryCacheText = JSON.stringify(
      queryClient
        .getQueryCache()
        .getAll()
        .map((query) => ({ key: query.queryKey, data: query.state.data })),
    );
    expect(queryCacheText).not.toContain(CREATED_SECRET);

    const mutationCacheText = JSON.stringify(
      queryClient
        .getMutationCache()
        .getAll()
        .map((mutation) => mutation.state),
    );
    expect(mutationCacheText).not.toContain(CREATED_SECRET);
  });

  it('announces a failed copy without hiding the key', async () => {
    installKeyStore(KEYS);
    const user = userEvent.setup();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    });
    renderApp();

    await openAccessKeys(user);
    const secretDialog = await createKeyThroughDialog(user);

    await user.click(within(secretDialog).getByRole('button', { name: 'Copy key' }));

    expect(
      await within(secretDialog).findByText('Copy failed. Select the key and copy it manually.'),
    ).toBeInTheDocument();
    expect(within(secretDialog).getByText(CREATED_SECRET)).toBeInTheDocument();
  });

  it('confirms revocation, sends DELETE, and refreshes the row status', async () => {
    const { fetchMock, deleteCalls } = installKeyStore(KEYS);
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const table = await screen.findByRole('table', { name: 'API keys' });
    const row = within(table).getByRole('row', { name: /Production/ });

    await user.click(within(row).getByRole('button', { name: 'Revoke Production' }));
    const dialog = await screen.findByRole('dialog', { name: 'Revoke API key' });
    expect(within(dialog).getByText(/Production/)).toBeInTheDocument();
    expect(within(dialog).getByText('lgw_live_prod')).toBeInTheDocument();

    const cancel = within(dialog).getByRole('button', { name: 'Cancel' });
    await waitFor(() => {
      expect(document.activeElement).toBe(cancel);
    });

    await user.click(within(dialog).getByRole('button', { name: 'Revoke key' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Revoke API key' })).not.toBeInTheDocument();
    });
    expect(deleteCalls).toEqual([PRODUCTION.id]);
    expect(await within(keysRegion()).findByText('API key revoked.')).toBeInTheDocument();

    const deleteCall = deleteKeyCalls(fetchMock)[0];
    expect(deleteCall).toBeDefined();
    expect(new Headers(deleteCall?.[1]?.headers).get('Authorization')).toBe('Bearer mk_test_123');

    await waitFor(() => {
      const updatedTable = within(keysRegion()).getByRole('table', { name: 'API keys' });
      const updatedRow = within(updatedTable).getByRole('row', { name: /Production/ });
      expect(within(updatedRow).getByText('Revoked')).toBeInTheDocument();
      expect(
        within(updatedRow).queryByRole('button', { name: 'Revoke Production' }),
      ).not.toBeInTheDocument();
    });
  });

  it('keeps the revoke dialog open on a 404 key error', async () => {
    const { fetchMock } = installKeyStore(KEYS, {
      'DELETE /api/v1/keys/:id': () =>
        apiError(404, 'key_not_found', 'API key not found or already revoked', 'req_revoke_404'),
    });
    const user = userEvent.setup();
    renderApp();

    await openAccessKeys(user);
    const table = await screen.findByRole('table', { name: 'API keys' });
    const row = within(table).getByRole('row', { name: /Production/ });

    await user.click(within(row).getByRole('button', { name: 'Revoke Production' }));
    const dialog = await screen.findByRole('dialog', { name: 'Revoke API key' });
    await user.click(within(dialog).getByRole('button', { name: 'Revoke key' }));

    expect(await within(dialog).findByText('Could not revoke API key')).toBeInTheDocument();
    expect(within(dialog).getByText('HTTP 404')).toBeInTheDocument();
    expect(within(dialog).getByText('key_not_found')).toBeInTheDocument();
    expect(within(dialog).getByText('req_revoke_404')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Revoke API key' })).toBeInTheDocument();
    expect(deleteKeyCalls(fetchMock)).toHaveLength(1);
  });

  it('discards key data and the one-time secret on disconnect', async () => {
    installKeyStore(KEYS);
    const { queryClient } = renderApp();
    const user = userEvent.setup();

    await openAccessKeys(user);
    const secretDialog = await createKeyThroughDialog(user);
    expect(within(secretDialog).getByText(CREATED_SECRET)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Disconnect' }));

    expect(await screen.findByText('Connect a master key to manage API keys.')).toBeInTheDocument();
    expect(await screen.findByText('Connect a master key to manage tenants.')).toBeInTheDocument();
    expect(screen.queryByText(CREATED_SECRET)).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await waitFor(() => {
      const remainingKeysQueries = queryClient
        .getQueryCache()
        .getAll()
        .filter((query) => String(query.queryKey[0]) === 'admin-keys');
      expect(remainingKeysQueries).toHaveLength(0);
    });

    const mutationCacheText = JSON.stringify(
      queryClient
        .getMutationCache()
        .getAll()
        .map((mutation) => mutation.state),
    );
    expect(mutationCacheText).not.toContain(CREATED_SECRET);
  });
});
