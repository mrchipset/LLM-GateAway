import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { adminQueryPrefixes } from '../lib/queryKeys';
import { connectWithKey } from './connectWithKey';
import { installFetchMock } from './fetchMock';
import { renderApp } from './renderApp';

const EXPECTED_ADMIN_PREFIXES = [
  'admin-models',
  'admin-tenants',
  'usage-summary',
  'usage-series',
  'usage-by-key',
  'admin-keys',
  'audit-sessions',
  'audit-session',
  'audit-request',
];

const LOADED_ADMIN_PREFIXES = EXPECTED_ADMIN_PREFIXES.filter(
  (prefix) => prefix !== 'admin-keys' && prefix !== 'audit-session' && prefix !== 'audit-request',
);

describe('admin query keys', () => {
  it('clears every admin query prefix on disconnect and restores connect prompts', async () => {
    installFetchMock();
    const { queryClient } = renderApp();
    const user = userEvent.setup();

    await connectWithKey(user);

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

    const adminPrefixes: string[] = adminQueryPrefixes.map(([prefix]) => prefix);
    expect(new Set(adminPrefixes)).toEqual(new Set(EXPECTED_ADMIN_PREFIXES));

    await user.click(screen.getByRole('button', { name: 'Disconnect' }));
    expect(
      await screen.findByText('Connect a master key to load the registry.'),
    ).toBeInTheDocument();

    await waitFor(() => {
      const remainingAdminQueries = queryClient
        .getQueryCache()
        .getAll()
        .filter((query) => EXPECTED_ADMIN_PREFIXES.includes(String(query.queryKey[0])));
      expect(remainingAdminQueries).toHaveLength(0);
    });

    await user.click(screen.getByRole('tab', { name: 'Usage' }));
    expect(await screen.findByText('Connect a master key to load usage.')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Access' }));
    expect(await screen.findByText('Connect a master key to manage tenants.')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Audit' }));
    expect(
      await screen.findByText('Connect a master key to view the audit log.'),
    ).toBeInTheDocument();
  });
});
