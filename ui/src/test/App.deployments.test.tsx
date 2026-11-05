import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { CreateDeploymentInput, ModelDeployment, ModelSummary } from '../api/client';
import { signIn } from './signIn';
import { installFetchMock, jsonResponse, toUrl, type Routes } from './fetchMock';
import { renderApp } from './renderApp';

const MODEL: ModelSummary = {
  id: 'chat-prod',
  provider: 'openai',
  upstream_model: 'gpt-4o-mini-2024-07-18',
  enabled: true,
  created_at: '2026-10-24T17:24:00Z',
};

const PRIMARY: ModelDeployment = {
  id: 'dddddddd-1111-4111-8111-111111111111',
  model_id: MODEL.id,
  name: 'primary',
  provider: 'openai',
  upstream_model: 'gpt-4o-mini-2024-07-18',
  weight: 80,
  enabled: true,
  credential_env: 'OPENAI_API_KEY',
  base_url: 'https://api.openai.com/v1',
  created_at: '2026-10-20T08:00:00Z',
};

const BACKUP: ModelDeployment = {
  id: 'dddddddd-2222-4222-8222-222222222222',
  model_id: MODEL.id,
  name: 'backup',
  provider: 'deepseek',
  upstream_model: 'deepseek-chat',
  weight: 20,
  enabled: false,
  credential_env: null,
  base_url: null,
  created_at: '2026-10-21T09:00:00Z',
};

function modelPayload(): Response {
  return jsonResponse({ items: [MODEL], total: 1, limit: 100, offset: 0 });
}

function deploymentPayload(items: ModelDeployment[]): Response {
  return jsonResponse({ model_id: MODEL.id, items });
}

function installDeploymentMock(
  deployments: ModelDeployment[],
  overrides: Routes = {},
  sessionOptions: Parameters<typeof installFetchMock>[1] = {},
): ReturnType<typeof installFetchMock> {
  let current = [...deployments];
  return installFetchMock(
    {
      '/api/v1/models': () => modelPayload(),
      'GET /api/v1/models/:id/deployments': () => deploymentPayload(current),
      'POST /api/v1/models/:id/deployments': (_url, init) => {
        const body = JSON.parse(String(init.body)) as CreateDeploymentInput;
        const created: ModelDeployment = {
          ...body,
          id: 'dddddddd-3333-4333-8333-333333333333',
          model_id: MODEL.id,
          credential_env: body.credential_env ?? null,
          base_url: body.base_url ?? null,
          created_at: '2026-10-25T12:00:00Z',
        };
        current = [...current, created];
        return jsonResponse(created, 201);
      },
      'PATCH /api/v1/deployments/:id': (url, init) => {
        const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
        const body = JSON.parse(String(init.body)) as Partial<ModelDeployment>;
        const existing = current.find((deployment) => deployment.id === id);
        if (existing === undefined) {
          return jsonResponse({ error: { message: 'Not found', code: 'not_found' } }, 404);
        }
        const updated: ModelDeployment = { ...existing, ...body };
        current = current.map((deployment) => (deployment.id === id ? updated : deployment));
        return jsonResponse(updated);
      },
      'DELETE /api/v1/deployments/:id': (url) => {
        const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
        current = current.filter((deployment) => deployment.id !== id);
        return new Response(null, { status: 204 });
      },
      ...overrides,
    },
    sessionOptions,
  );
}

function deploymentCalls(fetchMock: ReturnType<typeof installFetchMock>, method: string) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return (
      url.pathname.startsWith('/api/v1/deployments/') &&
      (init?.method ?? 'GET').toUpperCase() === method
    );
  });
}

async function openDeployments(user: ReturnType<typeof userEvent.setup>) {
  await signIn(user);
  const table = await screen.findByRole('table', { name: 'Registered models' });
  await user.click(within(table).getByRole('button', { name: 'Deployments for chat-prod' }));
  return screen.findByRole('dialog', { name: 'Deployments' });
}

describe('deployment editor', () => {
  it('lists targets with weight, status, credential variable name, and base URL', async () => {
    installDeploymentMock([PRIMARY, BACKUP]);
    const user = userEvent.setup();
    renderApp();

    const dialog = await openDeployments(user);

    expect(
      within(dialog).getByText(
        '请求按权重随机分流，失败会切换到其他部署，连续失败的部署进入冷却。',
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/names an environment variable/)).toBeInTheDocument();
    expect(within(dialog).getByText('primary')).toBeInTheDocument();
    expect(within(dialog).getByText('backup')).toBeInTheDocument();
    expect(within(dialog).getByText('80')).toBeInTheDocument();
    expect(within(dialog).getByText('20')).toBeInTheDocument();
    expect(within(dialog).getByText('OPENAI_API_KEY')).toBeInTheDocument();
    expect(within(dialog).getByText('https://api.openai.com/v1')).toBeInTheDocument();
    expect(within(dialog).getAllByText('Provider default')).toHaveLength(2);
    expect(within(dialog).getByText('2 deployments')).toBeInTheDocument();
  });

  it('creates a deployment with a credential variable name', async () => {
    const fetchMock = installDeploymentMock([PRIMARY]);
    const user = userEvent.setup();
    renderApp();

    const dialog = await openDeployments(user);
    await user.click(within(dialog).getByRole('button', { name: 'Add deployment' }));

    await user.type(within(dialog).getByLabelText('Name'), 'backup');
    await user.selectOptions(within(dialog).getByLabelText('Provider'), 'deepseek');
    await user.type(within(dialog).getByLabelText('Upstream model'), 'deepseek-chat ');
    await user.clear(within(dialog).getByLabelText('Weight (1–100)'));
    await user.type(within(dialog).getByLabelText('Weight (1–100)'), '40');
    await user.type(
      within(dialog).getByLabelText('Credential env (name only)'),
      'DEEPSEEK_API_KEY',
    );
    await user.type(
      within(dialog).getByLabelText('Base URL (optional)'),
      'https://api.deepseek.com/v1',
    );
    await user.click(within(dialog).getByRole('button', { name: 'Add deployment' }));

    expect(await within(dialog).findByText("Deployment 'backup' added.")).toBeInTheDocument();
    const postCalls = fetchMock.mock.calls.filter(
      ([input, init]) =>
        /^\/api\/v1\/models\/[^/]+\/deployments$/.test(toUrl(input).pathname) &&
        (init?.method ?? 'GET').toUpperCase() === 'POST',
    );
    expect(postCalls).toHaveLength(1);
    const call = postCalls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      name: 'backup',
      provider: 'deepseek',
      upstream_model: 'deepseek-chat',
      weight: 40,
      enabled: true,
      credential_env: 'DEEPSEEK_API_KEY',
      base_url: 'https://api.deepseek.com/v1',
    });

    expect(await within(dialog).findByText('backup')).toBeInTheDocument();
    expect(within(dialog).getByText('2 deployments')).toBeInTheDocument();
  });

  it('rejects a secret-shaped credential, an invalid weight, and a bad URL', async () => {
    installDeploymentMock([PRIMARY]);
    const user = userEvent.setup();
    renderApp();

    const dialog = await openDeployments(user);
    await user.click(within(dialog).getByRole('button', { name: 'Add deployment' }));

    await user.type(within(dialog).getByLabelText('Name'), 'backup');
    await user.type(within(dialog).getByLabelText('Upstream model'), 'deepseek-chat');
    await user.clear(within(dialog).getByLabelText('Weight (1–100)'));
    await user.type(within(dialog).getByLabelText('Weight (1–100)'), '0');
    await user.type(within(dialog).getByLabelText('Credential env (name only)'), 'sk-live-secret');
    await user.type(within(dialog).getByLabelText('Base URL (optional)'), 'ftp://example.com');
    await user.click(within(dialog).getByRole('button', { name: 'Add deployment' }));

    expect(
      await within(dialog).findByText('Enter a whole number from 1 to 100.'),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText('Use capitals, digits, and underscores, starting with a letter.'),
    ).toBeInTheDocument();
    expect(within(dialog).getByText('Use an http:// or https:// URL.')).toBeInTheDocument();
  });

  it('patches only changed fields and clears a credential variable explicitly', async () => {
    const fetchMock = installDeploymentMock([PRIMARY]);
    const user = userEvent.setup();
    renderApp();

    const dialog = await openDeployments(user);
    await user.click(within(dialog).getByRole('button', { name: 'Edit deployment primary' }));

    const weightInput = within(dialog).getByLabelText('Weight (1–100)');
    await user.clear(weightInput);
    await user.type(weightInput, '50');
    await user.click(within(dialog).getByRole('switch', { name: 'Enabled' }));
    await user.clear(within(dialog).getByLabelText('Credential env (name only)'));
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    expect(await within(dialog).findByText("Deployment 'primary' updated.")).toBeInTheDocument();
    const patchCalls = deploymentCalls(fetchMock, 'PATCH');
    expect(patchCalls).toHaveLength(1);
    const call = patchCalls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      weight: 50,
      enabled: false,
      credential_env: null,
    });
  });

  it('requires confirmation before deleting a deployment', async () => {
    const fetchMock = installDeploymentMock([PRIMARY, BACKUP]);
    const user = userEvent.setup();
    renderApp();

    const dialog = await openDeployments(user);
    await user.click(within(dialog).getByRole('button', { name: 'Delete deployment primary' }));

    expect(within(dialog).getByText(/This cannot be undone/)).toBeInTheDocument();
    expect(deploymentCalls(fetchMock, 'DELETE')).toHaveLength(0);

    await user.click(within(dialog).getByRole('button', { name: 'Delete deployment' }));

    expect(await within(dialog).findByText("Deployment 'primary' deleted.")).toBeInTheDocument();
    expect(deploymentCalls(fetchMock, 'DELETE')).toHaveLength(1);
    expect(within(dialog).queryByText('primary')).not.toBeInTheDocument();
    expect(within(dialog).getByText('1 deployment')).toBeInTheDocument();
  });

  it('hides deployment controls from an auditor', async () => {
    installDeploymentMock(
      [PRIMARY],
      {},
      { username: 'auditor', password: 'auditor-password', role: 'auditor' },
    );
    const user = userEvent.setup();
    renderApp();

    await signIn(user, { username: 'auditor', password: 'auditor-password' });

    expect(await screen.findByRole('table', { name: 'Registered models' })).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Deployments for chat-prod' }),
    ).not.toBeInTheDocument();
  });
});
