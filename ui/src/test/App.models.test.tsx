import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { connectWithKey } from './connectWithKey';
import { installFetchMock, jsonResponse, toUrl } from './fetchMock';
import { renderApp } from './renderApp';

const ENABLED_MODEL = {
  id: 'gpt-4o-mini',
  provider: 'openai',
  upstream_model: 'gpt-4o-mini-2024-07-18',
  enabled: true,
  created_at: '2026-10-24T17:24:00Z',
};

const MODELS = [
  ENABLED_MODEL,
  {
    id: 'legacy-chat',
    provider: 'openai',
    upstream_model: 'gpt-3.5-turbo',
    enabled: false,
    created_at: '2026-10-23T09:05:00Z',
  },
];

function payload(items: typeof MODELS, total = items.length) {
  return { items, total, limit: 100, offset: 0 };
}

function modelCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input]) => toUrl(input).pathname === '/api/v1/models');
}

describe('model registry', () => {
  it('renders every model with the total count and a distinct disabled state', async () => {
    installFetchMock({ '/api/v1/models': () => jsonResponse(payload(MODELS)) });
    const user = userEvent.setup();
    renderApp();

    await connectWithKey(user);
    const table = await screen.findByRole('table', { name: 'Registered models' });

    expect(await screen.findByText('2 models')).toBeInTheDocument();
    expect(within(table).getByText('gpt-4o-mini')).toBeInTheDocument();
    expect(within(table).getByText('gpt-4o-mini-2024-07-18')).toBeInTheDocument();
    expect(within(table).getByText('legacy-chat')).toBeInTheDocument();
    expect(within(table).getByText('Enabled')).toBeInTheDocument();
    expect(within(table).getByText('Disabled')).toBeInTheDocument();
  });

  it('shows how many models are rendered when the registry exceeds one page', async () => {
    installFetchMock({ '/api/v1/models': () => jsonResponse(payload(MODELS, 150)) });
    const user = userEvent.setup();
    renderApp();

    await connectWithKey(user);

    expect(await screen.findByText('Showing 2 of 150')).toBeInTheDocument();
    expect(screen.queryByText('150 models')).not.toBeInTheDocument();
  });

  it('shows the registration hint with a curl command when the registry is empty', async () => {
    installFetchMock();
    const user = userEvent.setup();
    renderApp();

    await connectWithKey(user);

    expect(await screen.findByText('No models registered')).toBeInTheDocument();
    expect(screen.getByText('0 models')).toBeInTheDocument();
    expect(screen.getByText(/GATEWAY_MASTER_KEY/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy command' })).toBeInTheDocument();
  });

  it('shows the HTTP status, message, code, and request id when the request is rejected', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/models': () =>
        jsonResponse(
          {
            error: {
              message: 'Invalid API key',
              type: 'authentication_error',
              param: null,
              code: 'invalid_api_key',
              request_id: 'req_abc123',
            },
          },
          401,
          { 'x-request-id': 'req_abc123' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    await connectWithKey(user);

    expect(await screen.findByText('Could not load models')).toBeInTheDocument();
    expect(screen.getByText('HTTP 401')).toBeInTheDocument();
    expect(screen.getByText('Invalid API key')).toBeInTheDocument();
    expect(screen.getByText('invalid_api_key')).toBeInTheDocument();
    expect(screen.getByText('req_abc123')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry loading models' }));

    await waitFor(() => {
      expect(modelCalls(fetchMock)).toHaveLength(2);
    });
  });

  it('renders one compact card per model with id, upstream model, and created time', async () => {
    const expectedCards = [
      { id: 'gpt-4o-mini', upstream: 'gpt-4o-mini-2024-07-18', created: 'Oct 24, 2026, 17:24 UTC' },
      { id: 'legacy-chat', upstream: 'gpt-3.5-turbo', created: 'Oct 23, 2026, 09:05 UTC' },
    ];
    installFetchMock({ '/api/v1/models': () => jsonResponse(payload(MODELS)) });
    const user = userEvent.setup();
    renderApp();

    await connectWithKey(user);
    await screen.findByRole('table', { name: 'Registered models' });

    const list = screen.getByRole('list');
    expect(within(list).getAllByRole('listitem')).toHaveLength(expectedCards.length);

    for (const expected of expectedCards) {
      const item = within(list).getByText(expected.id).closest('li');
      expect(item).not.toBeNull();
      if (item === null) continue;
      expect(within(item).getByText(expected.upstream)).toBeInTheDocument();
      expect(within(item).getByText(expected.created)).toBeInTheDocument();
    }
  });

  it('renders created_at in UTC so timestamps do not depend on the machine timezone', async () => {
    installFetchMock({ '/api/v1/models': () => jsonResponse(payload([ENABLED_MODEL])) });
    const user = userEvent.setup();
    renderApp();

    await connectWithKey(user);
    expect(await screen.findByRole('table', { name: 'Registered models' })).toBeInTheDocument();

    expect(screen.getAllByText('Oct 24, 2026, 17:24 UTC').length).toBeGreaterThan(0);
  });
});
