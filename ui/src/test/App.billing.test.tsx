import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  CreateModelPriceInput,
  ModelPrice,
  ModelSummary,
  TenantLimitsPatch,
  TenantSummary,
} from '../api/client';
import { signIn } from './signIn';
import { installFetchMock, jsonResponse, readTestCsrfToken, toUrl, type Routes } from './fetchMock';
import { renderApp } from './renderApp';

const FIXED_NOW = new Date('2026-10-25T12:00:00.000Z');

const MODEL: ModelSummary = {
  id: 'chat-prod',
  provider: 'openai',
  upstream_model: 'gpt-4o-mini',
  enabled: true,
  created_at: '2026-10-24T17:24:00Z',
};

const OLD_PRICE: ModelPrice = {
  id: 'price-old',
  model_id: 'chat-prod',
  input_per_million: '0.150000',
  cached_input_per_million: null,
  output_per_million: '0.600000',
  currency: 'USD',
  effective_from: '2026-10-01T00:00:00Z',
  created_at: '2026-10-01T00:00:00Z',
};

const NEW_PRICE: ModelPrice = {
  id: 'price-new',
  model_id: 'chat-prod',
  input_per_million: '0.280000',
  cached_input_per_million: '0.028000',
  output_per_million: '0.420000',
  currency: 'USD',
  effective_from: '2026-10-20T00:00:00Z',
  created_at: '2026-10-20T00:00:00Z',
};

const TENANT: TenantSummary = {
  id: 'tenant-acme',
  name: 'Acme',
  created_at: '2026-09-01T00:00:00Z',
  monthly_token_quota: 1_000_000,
  requests_per_minute: 60,
  audit_enabled: false,
  model_access_mode: 'all',
  plan_tokens: 1_000_000,
  plan_allow_overage: false,
  monthly_cost_budget: '50.00',
};

const BILLING = {
  tenant_id: 'tenant-acme',
  currency: 'USD',
  period_start: '2026-10-01T00:00:00Z',
  period_end: '2026-11-01T00:00:00Z',
  plan_tokens: 1_000_000,
  plan_allow_overage: false,
  monthly_cost_budget: '50.00',
  used_tokens: 1_500_000,
  covered_tokens: 1_000_000,
  billable_tokens: 500_000,
  requests: 120,
  list_cost: '12.500000',
  billed_cost: '6.250000',
  budget_remaining: '43.750000',
};

const USAGE_SUMMARY = {
  prompt_tokens: 1_200_000,
  completion_tokens: 300_000,
  cached_tokens: 100_000,
  total_tokens: 1_500_000,
  requests: 42,
  covered_tokens: 1_000_000,
  billable_tokens: 200_000,
  list_cost: '18.750000',
  billed_cost: '7.500000',
  by_model: [],
};

const USAGE_POINTS = [
  {
    bucket_start: '2026-10-01T00:00:00Z',
    prompt_tokens: 60,
    completion_tokens: 40,
    cached_tokens: 10,
    total_tokens: 100,
    requests: 2,
    covered_tokens: 50,
    billable_tokens: 10,
    list_cost: '4.000000',
    billed_cost: '5.000000',
  },
  {
    bucket_start: '2026-10-02T00:00:00Z',
    prompt_tokens: 0,
    completion_tokens: 0,
    cached_tokens: 0,
    total_tokens: 0,
    requests: 0,
    covered_tokens: 0,
    billable_tokens: 0,
    list_cost: '0.000000',
    billed_cost: '2.500000',
  },
];

const USAGE_KEYS = [
  {
    api_key_id: '11111111-1111-4111-8111-111111111111',
    name: 'Production key',
    key_prefix: 'sk-live-1234',
    prompt_tokens: 900_000,
    completion_tokens: 200_000,
    cached_tokens: 90_000,
    total_tokens: 1_100_000,
    requests: 30,
    covered_tokens: 800_000,
    billable_tokens: 250_000,
    list_cost: '14.000000',
    billed_cost: '3.250000',
  },
];

function pricePayload(items: ModelPrice[]) {
  return { items, total: items.length, limit: 50, offset: 0 };
}

function tenantPayload(tenant: TenantSummary, url: URL) {
  const limit = Number(url.searchParams.get('limit') ?? '100');
  const offset = Number(url.searchParams.get('offset') ?? '0');
  return jsonResponse({ items: [tenant], total: 1, limit, offset });
}

function installModelsMock(overrides: Routes = {}) {
  return installFetchMock({
    '/api/v1/models': () => jsonResponse({ items: [MODEL], total: 1, limit: 100, offset: 0 }),
    ...overrides,
  });
}

function priceRequests(fetchMock: ReturnType<typeof installFetchMock>, method: 'GET' | 'POST') {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return (
      url.pathname === '/api/v1/models/chat-prod/prices' &&
      (init?.method ?? 'GET').toUpperCase() === method
    );
  });
}

function lastJsonBody<T>(call: unknown[]): T {
  const init = call[1] as RequestInit | undefined;
  return JSON.parse(String(init?.body)) as T;
}

async function openModels(user: ReturnType<typeof userEvent.setup>) {
  await signIn(user);
  return screen.findByRole('table', { name: 'Registered models' });
}

async function openPricing(user: ReturnType<typeof userEvent.setup>) {
  const table = await openModels(user);
  await user.click(within(table).getByRole('button', { name: 'Pricing for chat-prod' }));
  return screen.findByRole('dialog', { name: 'Model pricing' });
}

async function openAccess(user: ReturnType<typeof userEvent.setup>) {
  await signIn(user);
  await user.click(await screen.findByRole('tab', { name: 'Access' }));
  await screen.findByRole('heading', { name: 'Tenants' });
  return screen.findByRole('table', { name: 'Tenants' });
}

async function openBilling(user: ReturnType<typeof userEvent.setup>) {
  const table = await openAccess(user);
  await user.click(within(table).getByRole('button', { name: 'Billing for Acme' }));
  return screen.findByRole('dialog', { name: 'Tenant billing' });
}

describe('model pricing', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(FIXED_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.style.overflow = '';
  });

  it('lists versions newest first and appends a new version with the entered values', async () => {
    let prices = [OLD_PRICE, NEW_PRICE];
    const fetchMock = installModelsMock({
      'GET /api/v1/models/:id/prices': () => jsonResponse(pricePayload(prices)),
      'POST /api/v1/models/:id/prices': (_url, init) => {
        const body = JSON.parse(String(init.body)) as CreateModelPriceInput;
        const created: ModelPrice = {
          id: 'price-created',
          model_id: 'chat-prod',
          input_per_million: body.input_per_million,
          cached_input_per_million: body.cached_input_per_million ?? null,
          output_per_million: body.output_per_million,
          currency: 'USD',
          effective_from: body.effective_from ?? '2026-10-25T12:00:00Z',
          created_at: '2026-10-25T12:00:00Z',
        };
        prices = [...prices, created];
        return jsonResponse(created, 201);
      },
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openPricing(user);
    const list = await within(dialog).findByRole('list', { name: 'Price versions' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Oct 20, 2026, 00:00 UTC');
    expect(rows[0]).toHaveTextContent('0.28');
    expect(rows[0]).toHaveTextContent('0.028');
    expect(rows[0]).toHaveTextContent('0.42');
    expect(rows[1]).toHaveTextContent('0.15');
    expect(rows[1]).toHaveTextContent('Same as input');
    expect(within(dialog).getByText(/Prices are per million tokens/)).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText('Input per million tokens'), {
      target: { value: '1.5' },
    });
    fireEvent.change(within(dialog).getByLabelText('Cached input per million tokens'), {
      target: { value: '0.15' },
    });
    fireEvent.change(within(dialog).getByLabelText('Output per million tokens'), {
      target: { value: '3' },
    });
    fireEvent.change(within(dialog).getByLabelText('Effective from'), {
      target: { value: '2026-11-01T00:00' },
    });
    await user.click(within(dialog).getByRole('button', { name: 'Add price version' }));

    expect(await within(dialog).findByText('Price version added.')).toBeInTheDocument();

    const postCalls = priceRequests(fetchMock, 'POST');
    expect(postCalls).toHaveLength(1);
    const call = postCalls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;
    const body = lastJsonBody<CreateModelPriceInput>(call);
    expect(body).toEqual({
      input_per_million: '1.5',
      cached_input_per_million: '0.15',
      output_per_million: '3',
      effective_from: new Date('2026-11-01T00:00').toISOString(),
    });
    expect(new Headers(call[1]?.headers).get('x-csrf-token')).toBe(readTestCsrfToken());

    await waitFor(() => {
      expect(priceRequests(fetchMock, 'GET')).toHaveLength(2);
    });
    expect(within(dialog).getByText('1.5')).toBeInTheDocument();
  });

  it('keeps the dialog open and shows code and request id on a duplicate effective time', async () => {
    installModelsMock({
      'GET /api/v1/models/:id/prices': () => jsonResponse(pricePayload([NEW_PRICE])),
      'POST /api/v1/models/:id/prices': () =>
        jsonResponse(
          {
            error: {
              message: 'A price version with this effective time already exists',
              type: 'invalid_request_error',
              param: 'effective_from',
              code: 'duplicate_price',
              request_id: 'req_duplicate_price',
            },
          },
          409,
          { 'x-request-id': 'req_duplicate_price' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openPricing(user);
    const input = within(dialog).getByLabelText('Input per million tokens');
    fireEvent.change(input, { target: { value: '0.3' } });
    fireEvent.change(within(dialog).getByLabelText('Output per million tokens'), {
      target: { value: '0.6' },
    });
    fireEvent.change(within(dialog).getByLabelText('Effective from'), {
      target: { value: '2026-10-20T00:00' },
    });
    await user.click(within(dialog).getByRole('button', { name: 'Add price version' }));

    expect(await within(dialog).findByText('Could not add price version')).toBeInTheDocument();
    expect(within(dialog).getByText('HTTP 409')).toBeInTheDocument();
    expect(
      within(dialog).getByText('A price version with this effective time already exists'),
    ).toBeInTheDocument();
    expect(within(dialog).getByText('duplicate_price')).toBeInTheDocument();
    expect(within(dialog).getByText('req_duplicate_price')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Model pricing' })).toBeInTheDocument();
    expect(input).toHaveValue(0.3);
    expect(within(dialog).getByText('0.28')).toBeInTheDocument();
  });

  it('blocks blank and negative prices before sending', async () => {
    const fetchMock = installModelsMock({
      'GET /api/v1/models/:id/prices': () => jsonResponse(pricePayload([NEW_PRICE])),
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openPricing(user);
    await user.click(within(dialog).getByRole('button', { name: 'Add price version' }));

    expect(
      await within(dialog).findByText('Enter the input price per million tokens.'),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText('Enter the output price per million tokens.'),
    ).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText('Input per million tokens'), {
      target: { value: '-1' },
    });
    fireEvent.change(within(dialog).getByLabelText('Output per million tokens'), {
      target: { value: '0.5' },
    });
    fireEvent.change(within(dialog).getByLabelText('Cached input per million tokens'), {
      target: { value: '-0.2' },
    });
    await user.click(within(dialog).getByRole('button', { name: 'Add price version' }));

    expect(
      await within(dialog).findByText(
        'Enter a non-negative decimal for the input price, for example 0.28.',
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        'Enter a non-negative decimal for the cached input price, for example 0.28.',
      ),
    ).toBeInTheDocument();
    expect(priceRequests(fetchMock, 'POST')).toHaveLength(0);
    expect(screen.getByRole('dialog', { name: 'Model pricing' })).toBeInTheDocument();
  });

  it('shows a loading state without hiding the model registry', async () => {
    let resolvePrices: (response: Response) => void = () => {};
    const pendingPrices = new Promise<Response>((resolve) => {
      resolvePrices = resolve;
    });
    installModelsMock({
      'GET /api/v1/models/:id/prices': () => pendingPrices,
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openPricing(user);
    expect(await within(dialog).findByText('Loading price versions…')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Registered models' })).toBeInTheDocument();

    await act(async () => {
      resolvePrices(jsonResponse(pricePayload([NEW_PRICE])));
    });

    const list = await within(dialog).findByRole('list', { name: 'Price versions' });
    expect(within(list).getByText('0.28')).toBeInTheDocument();
  });

  it('surfaces a price list failure with the code and request id', async () => {
    installModelsMock({
      'GET /api/v1/models/:id/prices': () =>
        jsonResponse(
          {
            error: {
              message: 'Price store unavailable',
              type: 'server_error',
              param: null,
              code: 'price_store_unavailable',
              request_id: 'req_price_500',
            },
          },
          500,
          { 'x-request-id': 'req_price_500' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openPricing(user);

    expect(await within(dialog).findByText('Could not load price versions')).toBeInTheDocument();
    expect(within(dialog).getByText('HTTP 500')).toBeInTheDocument();
    expect(within(dialog).getByText('Price store unavailable')).toBeInTheDocument();
    expect(within(dialog).getByText('price_store_unavailable')).toBeInTheDocument();
    expect(within(dialog).getByText('req_price_500')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Registered models' })).toBeInTheDocument();
  });
});

describe('tenant billing', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(FIXED_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.style.overflow = '';
  });

  function installBillingMock(
    options: {
      initialTenant?: TenantSummary;
      billing?: unknown;
      patch?: (body: TenantLimitsPatch, tenant: TenantSummary) => Response;
    } = {},
  ) {
    let tenant = { ...(options.initialTenant ?? TENANT) };
    const patchBodies: TenantLimitsPatch[] = [];
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => tenantPayload(tenant, url),
      'GET /api/v1/tenants/:id/billing': () => jsonResponse(options.billing ?? { ...BILLING }),
      'PATCH /api/v1/tenants/:id': (_url, init) => {
        const body = JSON.parse(String(init.body)) as TenantLimitsPatch;
        patchBodies.push(body);
        if (options.patch !== undefined) return options.patch(body, tenant);

        const updated: TenantSummary = { ...tenant };
        if (body.plan_tokens !== undefined) updated.plan_tokens = body.plan_tokens;
        if (body.plan_allow_overage !== undefined) {
          updated.plan_allow_overage = body.plan_allow_overage;
        }
        if (body.monthly_cost_budget !== undefined) {
          updated.monthly_cost_budget = body.monthly_cost_budget;
        }
        tenant = updated;
        return jsonResponse(updated);
      },
    });

    return { fetchMock, patchBodies, tenant: () => tenant };
  }

  it('shows the current period summary and saves plan, budget, and overage', async () => {
    const { fetchMock, patchBodies } = installBillingMock();
    const user = userEvent.setup();
    renderApp();

    const dialog = await openBilling(user);
    const period = await within(dialog).findByRole('region', { name: 'Current period' });

    expect(within(period).getByText('Oct 01, 2026 – Nov 01, 2026 · USD')).toBeInTheDocument();
    expect(within(period).getByText('1,000,000 tokens / month')).toBeInTheDocument();
    expect(within(period).getByText('1,500,000')).toBeInTheDocument();
    expect(within(period).getByText('1,000,000')).toBeInTheDocument();
    expect(within(period).getByText('500,000')).toBeInTheDocument();
    expect(within(period).getByText('USD 12.50')).toBeInTheDocument();
    expect(within(period).getByText('USD 6.25')).toBeInTheDocument();
    expect(within(period).getByText('USD 43.75')).toBeInTheDocument();
    expect(within(period).getByText('120')).toBeInTheDocument();

    expect(
      within(dialog).getByText('Inside the plan: free. Over the plan: billed at list price.'),
    ).toBeInTheDocument();

    const planInput = within(dialog).getByLabelText('Plan tokens');
    const budgetInput = within(dialog).getByLabelText('Monthly cost budget');
    expect(planInput).toHaveValue(1_000_000);
    expect(budgetInput).toHaveValue('50.00');

    await user.clear(planInput);
    fireEvent.change(planInput, { target: { value: '2000000' } });
    await user.clear(budgetInput);
    await user.type(budgetInput, '75.50');
    await user.click(within(dialog).getByRole('switch', { name: 'Allow overage' }));
    await user.click(within(dialog).getByRole('button', { name: 'Save billing' }));

    expect(await screen.findByText('Billing updated for Acme.')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    expect(patchBodies).toEqual([
      {
        plan_tokens: 2_000_000,
        monthly_cost_budget: '75.50',
        plan_allow_overage: true,
      },
    ]);
    const billingCalls = () =>
      fetchMock.mock.calls.filter(
        ([input]) => toUrl(input).pathname === '/api/v1/tenants/tenant-acme/billing',
      );
    await waitFor(() => {
      expect(billingCalls().length).toBeGreaterThan(1);
    });
    await waitFor(() => {
      const tenantCalls = fetchMock.mock.calls.filter(
        ([input]) => toUrl(input).pathname === '/api/v1/tenants',
      );
      expect(tenantCalls.length).toBeGreaterThan(1);
    });
  });

  it('sends explicit nulls when the plan and budget are cleared', async () => {
    const { patchBodies } = installBillingMock();
    const user = userEvent.setup();
    renderApp();

    const dialog = await openBilling(user);
    await within(dialog).findByRole('region', { name: 'Current period' });

    await user.clear(within(dialog).getByLabelText('Plan tokens'));
    await user.clear(within(dialog).getByLabelText('Monthly cost budget'));
    expect(
      within(dialog).getByText('Will clear: plan tokens and monthly cost budget.'),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Save billing' }));

    expect(await screen.findByText('Billing updated for Acme.')).toBeInTheDocument();
    expect(patchBodies).toEqual([{ plan_tokens: null, monthly_cost_budget: null }]);
  });

  it('shows a loading state and still shows the tenant table', async () => {
    let resolveBilling: (response: Response) => void = () => {};
    const pendingBilling = new Promise<Response>((resolve) => {
      resolveBilling = resolve;
    });
    installFetchMock({
      '/api/v1/tenants': (url) => tenantPayload(TENANT, url),
      'GET /api/v1/tenants/:id/billing': () => pendingBilling,
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openBilling(user);
    expect(await within(dialog).findByText('Loading billing summary…')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Tenants' })).toBeInTheDocument();

    await act(async () => {
      resolveBilling(jsonResponse({ ...BILLING }));
    });

    expect(
      await within(dialog).findByRole('region', { name: 'Current period' }),
    ).toBeInTheDocument();
  });

  it('surfaces a billing summary failure with the code and request id', async () => {
    installFetchMock({
      '/api/v1/tenants': (url) => tenantPayload(TENANT, url),
      'GET /api/v1/tenants/:id/billing': () =>
        jsonResponse(
          {
            error: {
              message: 'Billing store unavailable',
              type: 'server_error',
              param: null,
              code: 'billing_unavailable',
              request_id: 'req_billing_500',
            },
          },
          500,
          { 'x-request-id': 'req_billing_500' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openBilling(user);

    expect(
      await within(dialog).findByText('Could not load the billing summary'),
    ).toBeInTheDocument();
    expect(within(dialog).getByText('HTTP 500')).toBeInTheDocument();
    expect(within(dialog).getByText('billing_unavailable')).toBeInTheDocument();
    expect(within(dialog).getByText('req_billing_500')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Tenants' })).toBeInTheDocument();
  });
});

describe('usage costs', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(FIXED_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders list and billed cost in totals, by key, and beside the chart', async () => {
    installFetchMock({
      '/api/v1/tenants': (url) => tenantPayload(TENANT, url),
      '/api/v1/usage/summary': () => jsonResponse(USAGE_SUMMARY),
      '/api/v1/usage/series': () => jsonResponse({ bucket: 'day', points: USAGE_POINTS }),
      '/api/v1/usage/by-key': () => jsonResponse({ limit: 100, items: USAGE_KEYS }),
    });
    const user = userEvent.setup();
    renderApp();

    await signIn(user);
    await user.click(await screen.findByRole('tab', { name: 'Usage' }));

    const totals = await screen.findByRole('region', { name: 'Window totals' });
    expect(within(totals).getByText('List cost')).toBeInTheDocument();
    expect(within(totals).getByText('18.75')).toBeInTheDocument();
    expect(within(totals).getByText('Billed cost')).toBeInTheDocument();
    expect(within(totals).getByText('7.50')).toBeInTheDocument();
    expect(
      within(totals).getByText(
        'Billed cost counts tokens over the plan. Amounts use the stored price currency.',
      ),
    ).toBeInTheDocument();

    const chart = await screen.findByRole('list', { name: /Daily total tokens/ });
    expect(chart).toBeInTheDocument();
    expect(screen.getByText('Billed cost in this range: 7.50')).toBeInTheDocument();

    const table = await screen.findByRole('table', { name: 'Usage by API key' });
    for (const label of ['Covered', 'Billable', 'Billed cost']) {
      expect(within(table).getByRole('columnheader', { name: label })).toBeInTheDocument();
    }
    const row = within(table).getByRole('row', { name: /Production key/ });
    expect(within(row).getByText('800K')).toBeInTheDocument();
    expect(within(row).getByText('250K')).toBeInTheDocument();
    expect(within(row).getByText('3.25')).toBeInTheDocument();
  });
});
