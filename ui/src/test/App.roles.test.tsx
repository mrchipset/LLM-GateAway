import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { ApiKeySummary, ModelSummary, TenantSummary } from '../api/client';
import { installFetchMock, jsonResponse } from './fetchMock';
import { renderApp } from './renderApp';
import { signIn } from './signIn';

const MODEL: ModelSummary = {
  id: 'chat-prod',
  provider: 'openai',
  upstream_model: 'gpt-4o-mini',
  enabled: true,
  created_at: '2026-10-24T17:24:00Z',
};

const TENANT: TenantSummary = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Acme',
  created_at: '2026-09-01T00:00:00Z',
  monthly_token_quota: 1_000_000,
  requests_per_minute: 60,
  audit_enabled: true,
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
};

function installDataMock(options: Parameters<typeof installFetchMock>[1] = {}) {
  return installFetchMock(
    {
      '/api/v1/models': () => jsonResponse({ items: [MODEL], total: 1, limit: 100, offset: 0 }),
      '/api/v1/tenants': () => jsonResponse({ items: [TENANT], total: 1, limit: 100, offset: 0 }),
      '/api/v1/keys': () =>
        jsonResponse({ items: [KEY], total: 1, limit: 20, offset: 0, tenant_id: null }),
    },
    options,
  );
}

function tabNames() {
  return screen.queryAllByRole('tab').map((tab) => tab.textContent ?? '');
}

describe('role-aware console', () => {
  it('gives an auditor read-only access without any write controls', async () => {
    installDataMock({ username: 'auditor', password: 'auditor-password', role: 'auditor' });
    const user = userEvent.setup();
    renderApp();

    await signIn(user, { username: 'auditor', password: 'auditor-password' });

    expect(screen.getByText('Auditor')).toBeInTheDocument();
    expect(screen.getByText(/Read-only role/)).toBeInTheDocument();
    expect(tabNames()).toEqual(['Models', 'Usage', 'Access', 'Audit', 'Admin audit']);
    expect(screen.queryByRole('tab', { name: 'Admins' })).not.toBeInTheDocument();

    expect(await screen.findByRole('table', { name: 'Registered models' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Register model' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Pricing for chat-prod' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete chat-prod' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Access' }));
    const access = screen.getByRole('region', { name: 'Tenants' });
    await within(access).findByRole('table', { name: 'Tenants' });
    expect(within(access).queryByRole('button', { name: 'Create tenant' })).not.toBeInTheDocument();
    expect(
      within(access).queryByRole('button', { name: 'Edit limits for Acme' }),
    ).not.toBeInTheDocument();

    const keyRegion = screen.getByRole('region', { name: 'API keys' });
    await within(keyRegion).findByRole('table', { name: 'API keys' });
    expect(
      within(keyRegion).queryByRole('button', { name: 'Create API key' }),
    ).not.toBeInTheDocument();
    expect(
      within(keyRegion).queryByRole('button', { name: 'Revoke Production' }),
    ).not.toBeInTheDocument();
  });

  it('gives an operator the write surface but no audit or admin management', async () => {
    installDataMock({ username: 'operator', password: 'operator-password', role: 'operator' });
    const user = userEvent.setup();
    renderApp();

    await signIn(user, { username: 'operator', password: 'operator-password' });

    expect(screen.getByText('Operator')).toBeInTheDocument();
    expect(screen.queryByText(/Read-only role/)).not.toBeInTheDocument();
    expect(tabNames()).toEqual(['Models', 'Usage', 'Access']);
    expect(screen.queryByRole('tab', { name: 'Audit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Admins' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Admin audit' })).not.toBeInTheDocument();

    expect(await screen.findByRole('button', { name: 'Register model' })).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Access' }));
    expect(await screen.findByRole('button', { name: 'Create tenant' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Create API key' })).toBeInTheDocument();
  });

  it('gives an owner every section, including admin management and admin audit', async () => {
    installDataMock();
    const user = userEvent.setup();
    renderApp();

    await signIn(user);

    expect(screen.getByText('Owner')).toBeInTheDocument();
    expect(tabNames()).toEqual(['Models', 'Usage', 'Access', 'Audit', 'Admins', 'Admin audit']);
    expect(screen.getByRole('button', { name: 'Register model' })).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Admin audit' }));
    expect(await screen.findByRole('heading', { name: 'Admin audit' })).toBeInTheDocument();
  });
});
