import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { ModelSummary, ThroughputStats } from '../api/client';
import { installFetchMock, jsonResponse } from './fetchMock';
import { renderApp } from './renderApp';
import { signIn } from './signIn';

const CHAT: ModelSummary = {
  id: 'chat-prod',
  provider: 'openai',
  upstream_model: 'gpt-4o-mini-2024-07-18',
  enabled: true,
  created_at: '2026-10-24T17:24:00Z',
};

const LEGACY: ModelSummary = {
  id: 'legacy-chat',
  provider: 'openai',
  upstream_model: 'gpt-3.5-turbo',
  enabled: false,
  created_at: '2026-10-23T09:05:00Z',
};

const CHAT_THROUGHPUT: ThroughputStats = {
  provider: 'openai',
  model: 'chat-prod',
  samples: 3,
  prefill_tokens_per_second_p50: 279.6,
  prefill_tokens_per_second_p95: 310.1,
  decode_tokens_per_second_p50: 128.3,
  decode_tokens_per_second_p95: 150.9,
  last_observed_at: '2026-11-16T15:54:30.367824Z',
};

function modelPayload(items: ModelSummary[]) {
  return { items, total: items.length, limit: 100, offset: 0 };
}

function throughputPayload(items: ThroughputStats[]) {
  return { window_seconds: 900, items };
}

async function openRegistry(user: ReturnType<typeof userEvent.setup>) {
  await signIn(user);
  return screen.findByRole('table', { name: 'Registered models' });
}

function rowFor(table: HTMLElement, modelId: string): HTMLElement {
  const cell = within(table).getByRole('rowheader', { name: modelId });
  const row = cell.closest('tr');
  if (row === null) throw new Error(`No row for ${modelId}`);
  return row;
}

describe('model live speed', () => {
  it('shows the rounded decode speed for a model with throughput data', async () => {
    installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload([CHAT])),
      '/api/v1/throughput': () => jsonResponse(throughputPayload([CHAT_THROUGHPUT])),
    });
    const user = userEvent.setup();
    renderApp();

    const table = await openRegistry(user);

    expect(within(table).getByRole('columnheader', { name: /^Speed/ })).toBeInTheDocument();
    const row = rowFor(table, 'chat-prod');
    expect(await within(row).findByText('128 tok/s')).toBeInTheDocument();
    expect(within(row).getByText('prefill 280')).toBeInTheDocument();

    const cards = screen.getByRole('list', { name: 'Model cards' });
    expect(within(cards).getByText('128 dec · 280 pre tok/s')).toBeInTheDocument();
  });

  it('shows an em dash when a model has no streamed traffic in the window', async () => {
    installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload([CHAT, LEGACY])),
      '/api/v1/throughput': () => jsonResponse(throughputPayload([CHAT_THROUGHPUT])),
    });
    const user = userEvent.setup();
    renderApp();

    const table = await openRegistry(user);
    await within(rowFor(table, 'chat-prod')).findByText('128 tok/s');

    const legacyRow = rowFor(table, 'legacy-chat');
    expect(
      within(legacyRow).getByLabelText('No streamed requests in the last 15 minutes'),
    ).toHaveTextContent('—');
    expect(within(legacyRow).queryByText('0 tok/s')).not.toBeInTheDocument();
  });

  it('keeps the models table usable when the throughput request fails', async () => {
    installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload([CHAT])),
      '/api/v1/throughput': () =>
        jsonResponse(
          {
            error: {
              message: 'Throughput is unavailable',
              type: 'server_error',
              param: null,
              code: 'internal_error',
              request_id: 'req_throughput_failed',
            },
          },
          500,
          { 'x-request-id': 'req_throughput_failed' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    const table = await openRegistry(user);

    const row = rowFor(table, 'chat-prod');
    expect(
      await within(row).findByLabelText('No streamed requests in the last 15 minutes'),
    ).toHaveTextContent('—');
    expect(screen.queryByText('Could not load models')).not.toBeInTheDocument();
    expect(within(table).getByRole('rowheader', { name: 'chat-prod' })).toBeInTheDocument();
  });
});
