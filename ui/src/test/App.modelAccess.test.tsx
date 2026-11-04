import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type {
  ModelSummary,
  TenantModelAccess,
  TenantModelAccessInput,
  TenantSummary,
} from '../api/client';
import { connectWithKey } from './connectWithKey';
import { installFetchMock, jsonResponse, toUrl } from './fetchMock';
import { renderApp } from './renderApp';

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
  model_access_mode: 'allowlist',
};

const TENANTS = [ACME, SOLO];

const MODELS: ModelSummary[] = [
  {
    id: 'a-model',
    provider: 'openai',
    upstream_model: 'upstream-a',
    enabled: true,
    created_at: '2026-10-20T10:00:00Z',
  },
  {
    id: 'm-model',
    provider: 'fake',
    upstream_model: 'upstream-m',
    enabled: true,
    created_at: '2026-10-21T10:00:00Z',
  },
  {
    id: 'z-model',
    provider: 'deepseek',
    upstream_model: 'upstream-z',
    enabled: true,
    created_at: '2026-10-22T10:00:00Z',
  },
];

function modelPayload(items: ModelSummary[], total = items.length) {
  return { items, total, limit: 100, offset: 0 };
}

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

interface InstallOptions {
  access: (tenantId: string) => TenantModelAccess;
  putResponse?: (body: TenantModelAccessInput) => Response;
  putBodies?: TenantModelAccessInput[];
  modelsResponse?: () => Response;
}

function installAccessMock({
  access,
  putResponse,
  putBodies = [],
  modelsResponse,
}: InstallOptions) {
  return installFetchMock({
    '/api/v1/tenants': (url) => tenantPage(TENANTS, url),
    '/api/v1/models': modelsResponse ?? (() => jsonResponse(modelPayload(MODELS))),
    'GET /api/v1/tenants/:id/model-access': (url) => {
      const tenantId = decodeURIComponent(url.pathname.split('/')[4] ?? '');
      return jsonResponse(access(tenantId));
    },
    'PUT /api/v1/tenants/:id/model-access': (url, init) => {
      const tenantId = decodeURIComponent(url.pathname.split('/')[4] ?? '');
      const body = JSON.parse(String(init.body)) as TenantModelAccessInput;
      putBodies.push(body);
      if (putResponse !== undefined) return putResponse(body);
      return jsonResponse({ tenant_id: tenantId, ...body });
    },
  });
}

async function openAccess(user: ReturnType<typeof userEvent.setup>) {
  await connectWithKey(user);
  await user.click(await screen.findByRole('tab', { name: 'Access' }));
  return screen.findByRole('table', { name: 'Tenants' });
}

async function openAccessDialog(user: ReturnType<typeof userEvent.setup>, tenantName: string) {
  const table = await screen.findByRole('table', { name: 'Tenants' });
  await user.click(within(table).getByRole('button', { name: `Model access for ${tenantName}` }));
  return screen.findByRole('dialog', { name: 'Model access' });
}

function buttonCalls(fetchMock: ReturnType<typeof installFetchMock>, method: string) {
  return fetchMock.mock.calls.filter(
    ([input, init]) =>
      toUrl(input).pathname.endsWith('/model-access') &&
      (init?.method ?? 'GET').toUpperCase() === method,
  );
}

describe('tenant model access', () => {
  it('shows the stored policy in the tenant table and opens the dialog in that mode', async () => {
    installAccessMock({
      access: (tenantId) =>
        tenantId === SOLO.id
          ? { tenant_id: tenantId, mode: 'allowlist', model_ids: ['a-model'] }
          : { tenant_id: tenantId, mode: 'all', model_ids: [] },
    });
    const user = userEvent.setup();
    renderApp();

    const table = await openAccess(user);
    expect(within(table).getByText('All models')).toBeInTheDocument();
    expect(within(table).getByText('Allowlist')).toBeInTheDocument();

    const dialog = await openAccessDialog(user, 'Solo');

    expect(await within(dialog).findByRole('radio', { name: 'Allowlist' })).toBeChecked();
    expect(within(dialog).getByRole('radio', { name: 'All models' })).not.toBeChecked();
    expect(within(dialog).getByRole('checkbox', { name: /^a-model\b/ })).toBeChecked();
    expect(within(dialog).getByText('1 selected')).toBeInTheDocument();
  });

  it('warns that an empty allowlist blocks every model for the tenant', async () => {
    installAccessMock({
      access: (tenantId) => ({ tenant_id: tenantId, mode: 'all', model_ids: [] }),
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const dialog = await openAccessDialog(user, 'Acme');
    const allowlist = await within(dialog).findByRole('radio', { name: 'Allowlist' });

    await user.click(allowlist);

    expect(
      await within(dialog).findByText(
        'No models selected. Saving this policy blocks every model for this tenant.',
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText('0 selected')).toBeInTheDocument();
  });

  it('saves the allowlist with sorted model ids and refreshes the tenant list', async () => {
    const putBodies: TenantModelAccessInput[] = [];
    let tenants = TENANTS.map((tenant) => ({ ...tenant }));
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => tenantPage(tenants, url),
      '/api/v1/models': () => jsonResponse(modelPayload(MODELS)),
      'GET /api/v1/tenants/:id/model-access': (url) => {
        const tenantId = decodeURIComponent(url.pathname.split('/')[4] ?? '');
        return jsonResponse({ tenant_id: tenantId, mode: 'allowlist', model_ids: [] });
      },
      'PUT /api/v1/tenants/:id/model-access': (url, init) => {
        const tenantId = decodeURIComponent(url.pathname.split('/')[4] ?? '');
        const body = JSON.parse(String(init.body)) as TenantModelAccessInput;
        putBodies.push(body);
        tenants = tenants.map((tenant) =>
          tenant.id === tenantId ? { ...tenant, model_access_mode: body.mode } : tenant,
        );
        return jsonResponse({ tenant_id: tenantId, ...body });
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const dialog = await openAccessDialog(user, 'Acme');

    await within(dialog).findByRole('checkbox', { name: /^a-model\b/ });
    await user.click(within(dialog).getByRole('checkbox', { name: /^z-model\b/ }));
    await user.click(within(dialog).getByRole('checkbox', { name: /^a-model\b/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(putBodies).toEqual([{ mode: 'allowlist', model_ids: ['a-model', 'z-model'] }]);
    expect(await screen.findByText('Model access updated for Acme.')).toBeInTheDocument();

    expect(buttonCalls(fetchMock, 'PUT')).toHaveLength(1);
    await waitFor(() => {
      const updatedTable = screen.getByRole('table', { name: 'Tenants' });
      const row = within(updatedTable).getByRole('row', { name: /Acme/ });
      expect(within(row).getByText('Allowlist')).toBeInTheDocument();
    });
  });

  it('keeps the dialog open and shows the code and request id when the save is rejected', async () => {
    installAccessMock({
      access: (tenantId) => ({ tenant_id: tenantId, mode: 'allowlist', model_ids: ['m-model'] }),
      putResponse: () =>
        jsonResponse(
          {
            error: {
              message: "Model 'm-model' was not found",
              type: 'invalid_request_error',
              param: 'model_ids',
              code: 'model_not_found',
              request_id: 'req_model_missing',
            },
          },
          404,
          { 'x-request-id': 'req_model_missing' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const dialog = await openAccessDialog(user, 'Acme');
    await within(dialog).findByRole('checkbox', { name: /^m-model\b/ });

    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    expect(await within(dialog).findByText('Could not update model access')).toBeInTheDocument();
    expect(within(dialog).getByText('HTTP 404')).toBeInTheDocument();
    expect(within(dialog).getByText("Model 'm-model' was not found")).toBeInTheDocument();
    expect(within(dialog).getByText('model_not_found')).toBeInTheDocument();
    expect(within(dialog).getByText('req_model_missing')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Model access' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Save changes' })).toBeEnabled();
  });

  it('keeps the dialog usable when the model list fails to load', async () => {
    const putBodies: TenantModelAccessInput[] = [];
    installAccessMock({
      access: (tenantId) => ({ tenant_id: tenantId, mode: 'allowlist', model_ids: ['a-model'] }),
      putBodies,
      modelsResponse: () =>
        jsonResponse(
          {
            error: {
              message: 'Model store unavailable',
              type: 'server_error',
              param: null,
              code: 'model_store_unavailable',
              request_id: 'req_models_500',
            },
          },
          500,
          { 'x-request-id': 'req_models_500' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    await openAccess(user);
    const dialog = await openAccessDialog(user, 'Acme');

    expect(await within(dialog).findByText('Could not load models')).toBeInTheDocument();
    expect(within(dialog).getByText('model_store_unavailable')).toBeInTheDocument();
    expect(within(dialog).getByText('req_models_500')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('radio', { name: 'All models' }));
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(putBodies).toEqual([{ mode: 'all', model_ids: [] }]);
    expect(await screen.findByText('Model access updated for Acme.')).toBeInTheDocument();
  });

  it('moves focus into the dialog and returns it to the trigger on Escape', async () => {
    installAccessMock({
      access: (tenantId) => ({ tenant_id: tenantId, mode: 'all', model_ids: [] }),
    });
    const user = userEvent.setup();
    renderApp();

    const table = await openAccess(user);
    const trigger = within(table).getByRole('button', { name: 'Model access for Acme' });

    await user.click(trigger);
    const dialog = await screen.findByRole('dialog', { name: 'Model access' });
    await waitFor(() => {
      expect(document.activeElement).toBe(dialog);
    });

    await user.keyboard('{Escape}');

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(trigger);
    });
  });
});
