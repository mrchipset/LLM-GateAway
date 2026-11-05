import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type {
  ApiKeyLimitsPatch,
  ApiKeySummary,
  ModelSummary,
  TenantSummary,
  UpdateModelInput,
} from '../api/client';
import { installFetchMock, jsonResponse, readTestCsrfToken, toUrl } from './fetchMock';
import { renderApp } from './renderApp';
import { signIn } from './signIn';

const TENANT: TenantSummary = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Acme',
  created_at: '2026-09-01T00:00:00Z',
  monthly_token_quota: null,
  requests_per_minute: 60,
  audit_enabled: false,
  model_access_mode: 'all',
  plan_tokens: null,
  plan_allow_overage: false,
  monthly_cost_budget: null,
};

const KEY: ApiKeySummary = {
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

const MODEL: ModelSummary = {
  id: 'chat-prod',
  provider: 'openai',
  upstream_model: 'gpt-4o-mini-2024-07-18',
  enabled: true,
  created_at: '2026-10-24T17:24:00Z',
  requests_per_minute: 60,
  tokens_per_minute: 5_000,
};

const CAPABILITY_MODEL: ModelSummary = {
  ...MODEL,
  context_window: 128_000,
  max_output_tokens: 4_096,
  supports_tools: true,
  supports_streaming: false,
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

function modelPage(models: ModelSummary[]): Response {
  return jsonResponse({ items: models, total: models.length, limit: 100, offset: 0 });
}

async function openModelEdit(user: ReturnType<typeof userEvent.setup>) {
  await signIn(user);
  const table = await screen.findByRole('table', { name: 'Registered models' });
  await user.click(within(table).getByRole('button', { name: 'Edit chat-prod' }));
  return screen.findByRole('dialog', { name: 'Edit model' });
}

async function openKeyEdit(user: ReturnType<typeof userEvent.setup>) {
  await signIn(user);
  await user.click(await screen.findByRole('tab', { name: 'Access' }));
  const region = screen.getByRole('region', { name: 'API keys' });
  const table = await within(region).findByRole('table', { name: 'API keys' });
  await user.click(within(table).getByRole('button', { name: 'Edit limits for Production' }));
  return screen.findByRole('dialog', { name: 'Edit key limits' });
}

describe('console limit editing', () => {
  it('patches only changed key limits and sends null when a limit is cleared', async () => {
    let key = { ...KEY };
    const patchBodies: ApiKeyLimitsPatch[] = [];
    const fetchMock = installFetchMock({
      '/api/v1/tenants': (url) => tenantPage([TENANT], url),
      '/api/v1/keys': (url) => keyPage([key], url),
      'PATCH /api/v1/keys/:id': (_url, init) => {
        const body = JSON.parse(String(init.body)) as ApiKeyLimitsPatch;
        patchBodies.push(body);
        key = { ...key, ...body };
        return jsonResponse(key);
      },
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openKeyEdit(user);
    expect(within(dialog).getByLabelText('Requests per minute')).toHaveValue(30);
    expect(within(dialog).getByLabelText('Tokens per minute')).toHaveValue(100);
    expect(within(dialog).getByLabelText('Max concurrent requests')).toHaveValue(2);

    await user.clear(within(dialog).getByLabelText('Requests per minute'));
    await user.type(within(dialog).getByLabelText('Requests per minute'), '45');
    await user.clear(within(dialog).getByLabelText('Tokens per minute'));

    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([{ requests_per_minute: 45, tokens_per_minute: null }]);
    expect(Object.keys(patchBodies[0] ?? {}).sort()).toEqual([
      'requests_per_minute',
      'tokens_per_minute',
    ]);

    const patchCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        toUrl(input).pathname === '/api/v1/keys/aaaaaaaa-1111-4111-8111-111111111111' &&
        (init?.method ?? 'GET').toUpperCase() === 'PATCH',
    );
    expect(patchCall).toBeDefined();
    expect(new Headers(patchCall?.[1]?.headers).get('x-csrf-token')).toBe(readTestCsrfToken());

    const region = screen.getByRole('region', { name: 'API keys' });
    expect(await within(region).findByText('Key limits updated.')).toBeInTheDocument();
    const table = await within(region).findByRole('table', { name: 'API keys' });
    expect(within(table).getByText('45 req/min · 2 concurrent')).toBeInTheDocument();
    expect(within(table).queryByText(/tok\/min/)).not.toBeInTheDocument();
  });

  it('toggles enabled and clears a model limit with a partial patch', async () => {
    let models = [{ ...MODEL }];
    const patchBodies: UpdateModelInput[] = [];
    const fetchMock = installFetchMock({
      '/api/v1/models': () => modelPage(models),
      'PATCH /api/v1/models/:id': (_url, init) => {
        const body = JSON.parse(String(init.body)) as UpdateModelInput;
        patchBodies.push(body);
        models = models.map((model) => (model.id === MODEL.id ? { ...model, ...body } : model));
        return jsonResponse(models[0]);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await signIn(user);
    const table = await screen.findByRole('table', { name: 'Registered models' });
    await user.click(within(table).getByRole('button', { name: 'Edit chat-prod' }));

    const dialog = await screen.findByRole('dialog', { name: 'Edit model' });
    expect(within(dialog).getByLabelText('Provider')).toHaveValue('openai');
    expect(within(dialog).getByLabelText('Upstream model')).toHaveValue('gpt-4o-mini-2024-07-18');
    expect(within(dialog).getByLabelText('Requests per minute')).toHaveValue(60);
    expect(within(dialog).getByLabelText('Tokens per minute')).toHaveValue(5_000);

    await user.click(within(dialog).getByRole('switch', { name: 'Enabled' }));
    await user.clear(within(dialog).getByLabelText('Requests per minute'));
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([{ enabled: false, requests_per_minute: null }]);

    const patchCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        toUrl(input).pathname === '/api/v1/models/chat-prod' &&
        (init?.method ?? 'GET').toUpperCase() === 'PATCH',
    );
    expect(patchCall).toBeDefined();

    expect(await screen.findByText("Model 'chat-prod' updated.")).toBeInTheDocument();
    const updatedTable = await screen.findByRole('table', { name: 'Registered models' });
    const row = within(updatedTable).getByRole('row', { name: /chat-prod/ });
    expect(within(row).getByText('Disabled')).toBeInTheDocument();
    expect(within(row).getByText('5K tok/min')).toBeInTheDocument();
    expect(within(row).queryByText(/req\/min/)).not.toBeInTheDocument();
  });
});

describe('model routing edits', () => {
  it('patches provider and upstream model together and trims the upstream name', async () => {
    let models = [{ ...MODEL }];
    const patchBodies: UpdateModelInput[] = [];
    installFetchMock({
      '/api/v1/models': () => modelPage(models),
      'PATCH /api/v1/models/:id': (_url, init) => {
        const body = JSON.parse(String(init.body)) as UpdateModelInput;
        patchBodies.push(body);
        models = models.map((model) => (model.id === MODEL.id ? { ...model, ...body } : model));
        return jsonResponse(models[0]);
      },
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openModelEdit(user);
    await user.selectOptions(within(dialog).getByLabelText('Provider'), 'deepseek');
    const upstream = within(dialog).getByLabelText('Upstream model');
    await user.clear(upstream);
    await user.type(upstream, '  deepseek-chat-v3  ');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([{ provider: 'deepseek', upstream_model: 'deepseek-chat-v3' }]);
    expect(await screen.findByText("Model 'chat-prod' updated.")).toBeInTheDocument();
  });

  it('sends only the upstream model when the provider is untouched', async () => {
    let models = [{ ...MODEL }];
    const patchBodies: UpdateModelInput[] = [];
    installFetchMock({
      '/api/v1/models': () => modelPage(models),
      'PATCH /api/v1/models/:id': (_url, init) => {
        const body = JSON.parse(String(init.body)) as UpdateModelInput;
        patchBodies.push(body);
        models = models.map((model) => (model.id === MODEL.id ? { ...model, ...body } : model));
        return jsonResponse(models[0]);
      },
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openModelEdit(user);
    const upstream = within(dialog).getByLabelText('Upstream model');
    await user.clear(upstream);
    await user.type(upstream, 'gpt-4o-2024-11-20');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([{ upstream_model: 'gpt-4o-2024-11-20' }]);
    expect(Object.keys(patchBodies[0] ?? {})).toEqual(['upstream_model']);
  });

  it('blocks a blank upstream model before sending', async () => {
    const patchBodies: UpdateModelInput[] = [];
    installFetchMock({
      '/api/v1/models': () => modelPage([MODEL]),
      'PATCH /api/v1/models/:id': (_url, init) => {
        patchBodies.push(JSON.parse(String(init.body)) as UpdateModelInput);
        return jsonResponse(MODEL);
      },
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openModelEdit(user);
    await user.clear(within(dialog).getByLabelText('Upstream model'));
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    expect(await within(dialog).findByText('Enter the upstream model name.')).toBeInTheDocument();
    expect(patchBodies).toHaveLength(0);
    expect(screen.getByRole('dialog', { name: 'Edit model' })).toBeInTheDocument();
  });

  it('keeps the dialog open and explains the deployment conflict on 409', async () => {
    installFetchMock({
      '/api/v1/models': () => modelPage([MODEL]),
      'PATCH /api/v1/models/:id': () =>
        jsonResponse(
          {
            error: {
              message:
                "Delete the model's deployments before changing provider or upstream_model; deployments override these defaults",
              type: 'conflict_error',
              param: null,
              code: 'model_has_deployments',
              request_id: 'req_model_has_deployments',
            },
          },
          409,
          { 'x-request-id': 'req_model_has_deployments' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openModelEdit(user);
    await user.selectOptions(within(dialog).getByLabelText('Provider'), 'anthropic');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    expect(await within(dialog).findByText('Could not update model')).toBeInTheDocument();
    expect(within(dialog).getByText('HTTP 409')).toBeInTheDocument();
    expect(within(dialog).getByText('model_has_deployments')).toBeInTheDocument();
    expect(within(dialog).getByText('req_model_has_deployments')).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        '该模型仍有部署。请先在「Deployments」对话框中删除全部部署，再保存 Provider 或上游模型的修改。',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Edit model' })).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Provider')).toHaveValue('anthropic');
    expect(within(dialog).getByRole('button', { name: 'Save changes' })).toBeEnabled();
  });
});

describe('model capabilities', () => {
  it('sends only changed capability fields and clears numbers with null', async () => {
    let models = [{ ...CAPABILITY_MODEL }];
    const patchBodies: UpdateModelInput[] = [];
    installFetchMock({
      '/api/v1/models': () => modelPage(models),
      'PATCH /api/v1/models/:id': (_url, init) => {
        const body = JSON.parse(String(init.body)) as UpdateModelInput;
        patchBodies.push(body);
        models = models.map((model) => (model.id === MODEL.id ? { ...model, ...body } : model));
        return jsonResponse(models[0]);
      },
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openModelEdit(user);
    expect(within(dialog).getByLabelText('Context window')).toHaveValue(128_000);
    expect(within(dialog).getByLabelText('Max output tokens')).toHaveValue(4_096);
    expect(within(dialog).getByRole('switch', { name: 'Tool use' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(within(dialog).getByRole('switch', { name: 'Streaming' })).toHaveAttribute(
      'aria-checked',
      'false',
    );

    await user.clear(within(dialog).getByLabelText('Context window'));
    await user.clear(within(dialog).getByLabelText('Max output tokens'));
    await user.type(within(dialog).getByLabelText('Max output tokens'), '2048');
    await user.click(within(dialog).getByRole('switch', { name: 'Tool use' }));
    await user.click(within(dialog).getByRole('switch', { name: 'Streaming' }));
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([
      {
        context_window: null,
        max_output_tokens: 2048,
        supports_tools: false,
        supports_streaming: true,
      },
    ]);
  });
});

describe('read-only console actions', () => {
  it('hides key and model edit actions from a read-only role', async () => {
    installFetchMock(
      {
        '/api/v1/tenants': (url) => tenantPage([TENANT], url),
        '/api/v1/keys': (url) => keyPage([KEY], url),
        '/api/v1/models': () => modelPage([MODEL]),
      },
      { username: 'auditor', password: 'auditor-password', role: 'auditor' },
    );
    const user = userEvent.setup();
    renderApp();

    await signIn(user, { username: 'auditor', password: 'auditor-password' });

    const models = await screen.findByRole('table', { name: 'Registered models' });
    expect(
      within(models).queryByRole('button', { name: 'Edit chat-prod' }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Access' }));
    const region = screen.getByRole('region', { name: 'API keys' });
    const keys = await within(region).findByRole('table', { name: 'API keys' });
    expect(
      within(keys).queryByRole('button', { name: 'Edit limits for Production' }),
    ).not.toBeInTheDocument();
    expect(
      within(keys).queryByRole('button', { name: 'Revoke Production' }),
    ).not.toBeInTheDocument();
    expect(within(keys).getByText('30 req/min · 100 tok/min · 2 concurrent')).toBeInTheDocument();
  });
});
