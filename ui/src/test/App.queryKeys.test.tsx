import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { adminQueryPrefixes } from '../lib/queryKeys';
import { installFetchMock } from './fetchMock';
import { renderApp } from './renderApp';
import { signIn } from './signIn';

const EXPECTED_ADMIN_PREFIXES = [
  'admin-models',
  'admin-model-prices',
  'admin-tenants',
  'admin-tenant-billing',
  'admin-model-access',
  'usage-summary',
  'usage-series',
  'usage-by-key',
  'admin-keys',
  'audit-sessions',
  'audit-session',
  'audit-request',
  'admin-admins',
  'admin-audit-events',
];

const LOADED_ADMIN_PREFIXES = EXPECTED_ADMIN_PREFIXES.filter(
  (prefix) =>
    prefix !== 'admin-model-prices' &&
    prefix !== 'admin-model-access' &&
    prefix !== 'admin-tenant-billing' &&
    prefix !== 'audit-session' &&
    prefix !== 'audit-request',
);

describe('admin query keys', () => {
  it('clears every admin query prefix on sign out and returns to login', async () => {
    installFetchMock();
    const { queryClient } = renderApp();
    const user = userEvent.setup();

    await signIn(user);

    await waitFor(() => {
      const firstKeys = new Set(
        queryClient
          .getQueryCache()
          .getAll()
          .map((query) => String(query.queryKey[0])),
      );
      for (const prefix of LOADED_ADMIN_PREFIXES) {
        expect(firstKeys.has(prefix), `${prefix} query should be cached`).toBe(true);
      }
    });

    const adminPrefixes: string[] = adminQueryPrefixes.map(([prefix]) => String(prefix));
    expect(new Set(adminPrefixes)).toEqual(new Set(EXPECTED_ADMIN_PREFIXES));

    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();

    await waitFor(() => {
      const remainingAdminQueries = queryClient
        .getQueryCache()
        .getAll()
        .filter((query) => EXPECTED_ADMIN_PREFIXES.includes(String(query.queryKey[0])));
      expect(remainingAdminQueries).toHaveLength(0);
    });

    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
  });
});
