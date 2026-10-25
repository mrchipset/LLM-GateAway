import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { connectWithKey } from './connectWithKey';
import { installFetchMock, jsonResponse, toUrl } from './fetchMock';
import { renderApp } from './renderApp';

function modelCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input]) => toUrl(input).pathname === '/api/v1/models');
}

describe('master key connection', () => {
  it('does not request models until a master key is connected', async () => {
    const fetchMock = installFetchMock();
    renderApp();

    expect(
      await screen.findByText('Connect a master key to load the registry.'),
    ).toBeInTheDocument();
    expect(modelCalls(fetchMock)).toHaveLength(0);
  });

  it('sends the bearer token to the admin models endpoint after connecting', async () => {
    const fetchMock = installFetchMock();
    const user = userEvent.setup();
    renderApp();

    await connectWithKey(user, 'mk_test_123');

    await waitFor(() => {
      expect(modelCalls(fetchMock)).toHaveLength(1);
    });

    const call = modelCalls(fetchMock)[0];
    expect(call).toBeDefined();
    if (call === undefined) return;

    const [input, init] = call;
    const url = toUrl(input);
    expect(`${url.pathname}${url.search}`).toBe('/api/v1/models?limit=100&offset=0');
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer mk_test_123');
  });

  it('moves focus to the key status on connect and back to the key input on disconnect', async () => {
    installFetchMock();
    const user = userEvent.setup();
    renderApp();

    await connectWithKey(user);

    const status = await screen.findByRole('group', { name: 'Master key loaded' });
    expect(document.activeElement).toBe(status);

    await user.click(screen.getByRole('button', { name: 'Disconnect' }));

    const input = await screen.findByLabelText('Master key');
    expect(document.activeElement).toBe(input);
  });

  it('marks the master key rejected on a 401 and clears the mark after a successful refetch', async () => {
    installFetchMock({
      '/api/v1/models': () =>
        jsonResponse(
          {
            error: {
              message: 'Invalid API key',
              type: 'authentication_error',
              param: null,
              code: 'invalid_api_key',
              request_id: 'req_rejected',
            },
          },
          401,
          { 'x-request-id': 'req_rejected' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    await connectWithKey(user);

    expect(await screen.findByText('Master key rejected')).toBeInTheDocument();
    expect(screen.queryByText('Master key loaded')).not.toBeInTheDocument();
    expect(
      screen.getByText('Disconnect, then connect with another master key.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Master key rejected' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Disconnect' })).toBeInTheDocument();

    installFetchMock({
      '/api/v1/models': () =>
        jsonResponse({
          items: [
            {
              id: 'gpt-4o-mini',
              provider: 'openai',
              upstream_model: 'gpt-4o-mini',
              enabled: true,
              created_at: '2026-10-24T17:24:00Z',
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
        }),
    });
    await user.click(screen.getByRole('button', { name: 'Retry loading models' }));

    expect(await screen.findByText('Master key loaded')).toBeInTheDocument();
    expect(screen.queryByText('Master key rejected')).not.toBeInTheDocument();
    expect(await screen.findByRole('table', { name: 'Registered models' })).toBeInTheDocument();
  });

  it('keeps the master key out of browser storage and clears it on disconnect', async () => {
    const masterKey = 'sk-gw-super-secret';
    installFetchMock({
      '/api/v1/models': () =>
        jsonResponse({
          items: [
            {
              id: 'gpt-4o-mini',
              provider: 'openai',
              upstream_model: 'gpt-4o-mini',
              enabled: true,
              created_at: '2026-10-24T17:24:00Z',
            },
          ],
          total: 1,
          limit: 100,
          offset: 0,
        }),
    });
    const user = userEvent.setup();
    renderApp();

    await connectWithKey(user, masterKey);
    expect(await screen.findByText('Master key loaded')).toBeInTheDocument();
    expect(await screen.findByRole('table', { name: 'Registered models' })).toBeInTheDocument();

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe('');
    expect(document.body.textContent).not.toContain(masterKey);
    expect(window.location.href).not.toContain(masterKey);

    await user.click(screen.getByRole('button', { name: 'Disconnect' }));

    expect(
      await screen.findByText('Connect a master key to load the registry.'),
    ).toBeInTheDocument();
    expect(screen.queryByDisplayValue(masterKey)).not.toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Registered models' })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(masterKey);
  });
});
