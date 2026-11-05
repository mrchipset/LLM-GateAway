import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type {
  ApiKeySummary,
  CreateApiKeyInput,
  CreateModelInput,
  CreatedApiKey,
  ModelSummary,
  TenantLimitsPatch,
  TenantSummary,
} from '../api/client';
import { signIn } from './signIn';
import { installFetchMock, jsonResponse, toUrl } from './fetchMock';
import { renderApp } from './renderApp';

const TENANT: TenantSummary = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Acme',
  created_at: '2026-09-01T00:00:00Z',
  monthly_token_quota: null,
  requests_per_minute: 60,
  tokens_per_minute: 1_000,
  max_concurrent_requests: 8,
  audit_retention_days: 30,
  audit_enabled: false,
  model_access_mode: 'all',
  plan_tokens: null,
  plan_allow_overage: false,
  monthly_cost_budget: null,
};

const LIMITED_KEY: ApiKeySummary = {
  id: 'aaaaaaaa-1111-4111-8111-111111111111',
  tenant_id: TENANT.id,
  name: 'Production',
  key_prefix: 'lgw_live_prod',
  created_at: '2026-10-01T08:15:00Z',
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
  requests_per_minute: 30,
  tokens_per_minute: 100,
  max_concurrent_requests: 2,
};

function tenantPage(tenants: TenantSummary[], url: URL): Response {
  const limit = Number(url.searchParams.get('limit') ?? '100');
  const offset = Number(url.searchParams.get('offset') ?? '0');
  return jsonResponse({
    items: tenants.slice(offset, offset + limit),
    total: tenants.length,
    limit,
    offset,
  });
}

function keyPage(keys: ApiKeySummary[], url: URL): Response {
  const limit = Number(url.searchParams.get('limit') ?? '20');
  const offset = Number(url.searchParams.get('offset') ?? '0');
  return jsonResponse({
    items: keys.slice(offset, offset + limit),
    total: keys.length,
    limit,
    offset,
    tenant_id: null,
  });
}

describe('limit fields', () => {
  it('patches the new tenant limits and shows them without opening the dialog', async () => {
    let tenant = { ...TENANT };
    const patchBodies: TenantLimitsPatch[] = [];
    installFetchMock({
      '/api/v1/tenants': (url) => tenantPage([tenant], url),
      'PATCH /api/v1/tenants/:id': (_url, init) => {
        const body = JSON.parse(String(init.body)) as TenantLimitsPatch;
        patchBodies.push(body);
        tenant = { ...tenant, ...body };
        return jsonResponse(tenant);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await signIn(user);
    await user.click(await screen.findByRole('tab', { name: 'Access' }));
    const region = screen.getByRole('region', { name: 'Tenants' });
    const table = await within(region).findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant limits' });

    expect(
      within(dialog).getByText(
        '留空表示继承全局默认保留期；0 表示合规保留（永不自动删除）；正数表示保留天数。',
      ),
    ).toBeInTheDocument();

    const tokensInput = within(dialog).getByLabelText('Tokens per minute');
    const concurrentInput = within(dialog).getByLabelText('Max concurrent requests');
    const retentionInput = within(dialog).getByLabelText('Audit retention (days)');

    expect(tokensInput).toHaveValue(1000);
    expect(concurrentInput).toHaveValue(8);
    expect(retentionInput).toHaveValue(30);

    await user.clear(tokensInput);
    await user.type(tokensInput, '2500000');
    await user.clear(concurrentInput);
    await user.type(concurrentInput, '12');
    await user.clear(retentionInput);
    await user.type(retentionInput, '0');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([
      {
        tokens_per_minute: 2_500_000,
        max_concurrent_requests: 12,
        audit_retention_days: 0,
      },
    ]);

    const updatedTable = await within(region).findByRole('table', { name: 'Tenants' });
    const row = within(updatedTable).getByRole('row', { name: /Acme/ });
    expect(within(row).getByTitle('2,500,000 tokens per minute')).toBeInTheDocument();
    expect(within(row).getByTitle('12 concurrent requests')).toBeInTheDocument();
    expect(within(row).getByTitle('Audit retention: Legal hold')).toBeInTheDocument();
  });

  it('rejects an invalid retention value before sending', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => tenantPage([TENANT], url),
    });
    const user = userEvent.setup();
    renderApp();

    await signIn(user);
    await user.click(await screen.findByRole('tab', { name: 'Access' }));
    const region = screen.getByRole('region', { name: 'Tenants' });
    const table = await within(region).findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit tenant limits' });
    const retentionInput = within(dialog).getByLabelText('Audit retention (days)');

    await user.clear(retentionInput);
    await user.type(retentionInput, '-1');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    expect(
      await within(dialog).findByText('Enter a whole number of 0 or more.'),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(0);
  });

  it('creates a tenant with the optional limits', async () => {
    let tenants = [TENANT];
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => tenantPage(tenants, url),
      'POST /api/v1/tenants': (_url, init) => {
        const body = JSON.parse(String(init.body)) as { name: string };
        const created: TenantSummary = {
          id: '33333333-3333-4333-8333-333333333333',
          name: body.name,
          created_at: '2026-10-25T12:00:00Z',
          monthly_token_quota: null,
          requests_per_minute: null,
          tokens_per_minute: 5000,
          max_concurrent_requests: 4,
          audit_retention_days: 0,
          audit_enabled: false,
          model_access_mode: 'all',
          plan_tokens: null,
          plan_allow_overage: false,
          monthly_cost_budget: null,
        };
        tenants = [created, ...tenants];
        return jsonResponse(created, 201);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await signIn(user);
    await user.click(await screen.findByRole('tab', { name: 'Access' }));
    const region = screen.getByRole('region', { name: 'Tenants' });
    await within(region).findByRole('table', { name: 'Tenants' });

    await user.type(within(region).getByLabelText('Tenant name'), 'New Tenant');
    await user.type(within(region).getByLabelText('Tokens per minute'), '5000');
    await user.type(within(region).getByLabelText('Max concurrent requests'), '4');
    await user.type(within(region).getByLabelText('Audit retention (days)'), '0');
    await user.click(within(region).getByRole('button', { name: 'Create tenant' }));

    expect(await within(region).findByText('Tenant created.')).toBeInTheDocument();
    const createCalls = fetchMock.mock.calls.filter(
      ([input, init]) =>
        toUrl(input).pathname === '/api/v1/tenants' &&
        (init?.method ?? 'GET').toUpperCase() === 'POST',
    );
    expect(createCalls).toHaveLength(1);
    const call = createCalls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      name: 'New Tenant',
      tokens_per_minute: 5000,
      max_concurrent_requests: 4,
      audit_retention_days: 0,
    });
  });

  it('sends per-key limits on creation and blocks zero values', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => tenantPage([TENANT], url),
      'POST /api/v1/keys': (_url, init) => {
        const body = JSON.parse(String(init.body)) as CreateApiKeyInput;
        const created: CreatedApiKey = {
          id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          tenant_id: body.tenant_id,
          name: body.name,
          key: 'lgw_live_created_secret',
          key_prefix: 'lgw_live_created',
          created_at: '2026-10-25T12:00:00Z',
          expires_at: null,
          requests_per_minute: body.requests_per_minute ?? null,
          tokens_per_minute: body.tokens_per_minute ?? null,
          max_concurrent_requests: body.max_concurrent_requests ?? null,
        };
        return jsonResponse(created, 201);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await signIn(user);
    await user.click(await screen.findByRole('tab', { name: 'Access' }));
    await user.click(await screen.findByRole('button', { name: 'Create API key' }));
    const dialog = await screen.findByRole('dialog', { name: 'Create API key' });

    await user.selectOptions(within(dialog).getByLabelText('Tenant'), TENANT.id);
    await user.type(within(dialog).getByLabelText('Key name'), 'Nightly');

    const rateInput = within(dialog).getByLabelText('Requests per minute');
    await user.type(rateInput, '0');
    await user.click(within(dialog).getByRole('button', { name: 'Create key' }));
    expect(
      await within(dialog).findByText('Enter a whole number of 1 or more.'),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) =>
          toUrl(input).pathname === '/api/v1/keys' &&
          (init?.method ?? 'GET').toUpperCase() === 'POST',
      ),
    ).toHaveLength(0);

    await user.clear(rateInput);
    await user.type(rateInput, '25');
    await user.type(within(dialog).getByLabelText('Tokens per minute'), '4000');
    await user.type(within(dialog).getByLabelText('Max concurrent'), '3');
    await user.click(within(dialog).getByRole('button', { name: 'Create key' }));

    expect(await screen.findByRole('dialog', { name: 'API key created' })).toBeInTheDocument();
    const createCalls = fetchMock.mock.calls.filter(
      ([input, init]) =>
        toUrl(input).pathname === '/api/v1/keys' &&
        (init?.method ?? 'GET').toUpperCase() === 'POST',
    );
    expect(createCalls).toHaveLength(1);
    const call = createCalls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      name: 'Nightly',
      tenant_id: TENANT.id,
      requests_per_minute: 25,
      tokens_per_minute: 4000,
      max_concurrent_requests: 3,
    });
  });

  it('shows configured key limits in the directory', async () => {
    installFetchMock({
      '/api/v1/tenants': (url) => tenantPage([TENANT], url),
      '/api/v1/keys': (url) => keyPage([LIMITED_KEY], url),
    });
    const user = userEvent.setup();
    renderApp();

    await signIn(user);
    await user.click(await screen.findByRole('tab', { name: 'Access' }));
    const region = screen.getByRole('region', { name: 'API keys' });
    const table = await within(region).findByRole('table', { name: 'API keys' });

    expect(within(table).getByText('30 req/min · 100 tok/min · 2 concurrent')).toBeInTheDocument();
  });

  it('sends model limits on registration and shows them in the registry', async () => {
    let models: ModelSummary[] = [];
    const fetchMock = installFetchMock({
      '/api/v1/models': () =>
        jsonResponse({ items: models, total: models.length, limit: 100, offset: 0 }),
      'POST /api/v1/models': (_url, init) => {
        const body = JSON.parse(String(init.body)) as CreateModelInput;
        const created: ModelSummary = {
          ...body,
          created_at: '2026-10-25T12:00:00Z',
          requests_per_minute: body.requests_per_minute ?? null,
          tokens_per_minute: body.tokens_per_minute ?? null,
        };
        models = [created];
        return jsonResponse(created, 201);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await signIn(user);
    await user.click(await screen.findByRole('button', { name: 'Register model' }));
    const dialog = await screen.findByRole('dialog', { name: 'Register model' });

    await user.type(within(dialog).getByLabelText('Model id'), 'chat-prod');
    await user.type(within(dialog).getByLabelText('Upstream model'), 'gpt-4o-mini');
    await user.type(within(dialog).getByLabelText('Requests per minute'), '60');
    await user.type(within(dialog).getByLabelText('Tokens per minute'), '500000');
    await user.click(within(dialog).getByRole('button', { name: 'Register model' }));

    expect(await screen.findByText("Model 'chat-prod' registered.")).toBeInTheDocument();
    const postCalls = fetchMock.mock.calls.filter(
      ([input, init]) =>
        toUrl(input).pathname === '/api/v1/models' &&
        (init?.method ?? 'GET').toUpperCase() === 'POST',
    );
    expect(postCalls).toHaveLength(1);
    const call = postCalls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      id: 'chat-prod',
      provider: 'openai',
      upstream_model: 'gpt-4o-mini',
      enabled: true,
      requests_per_minute: 60,
      tokens_per_minute: 500000,
    });

    const table = await screen.findByRole('table', { name: 'Registered models' });
    expect(within(table).getByText('60 req/min · 500K tok/min')).toBeInTheDocument();
  });
});
