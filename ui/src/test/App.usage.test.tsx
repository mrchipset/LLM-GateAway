import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { connectWithKey } from './connectWithKey';
import { installFetchMock, jsonResponse, toUrl, type Routes } from './fetchMock';
import { renderApp } from './renderApp';

const FIXED_NOW = new Date('2026-10-25T12:00:00.000Z');

const USAGE_PATHS = [
  '/api/v1/usage/summary',
  '/api/v1/usage/series',
  '/api/v1/usage/by-key',
] as const;

const TENANTS = [
  {
    id: 'tenant-a',
    name: 'Acme',
    created_at: '2026-09-01T00:00:00Z',
    monthly_token_quota: 1_000_000,
    requests_per_minute: 60,
  },
  {
    id: 'tenant-b',
    name: 'Solo',
    created_at: '2026-09-02T00:00:00Z',
    monthly_token_quota: null,
    requests_per_minute: null,
  },
];

const SUMMARY = {
  prompt_tokens: 1_200_000,
  completion_tokens: 300_000,
  cached_tokens: 100_000,
  total_tokens: 1_500_000,
  requests: 42,
  by_model: [],
};

const SERIES = {
  bucket: 'day',
  points: [
    {
      bucket_start: '2026-10-01T00:00:00Z',
      prompt_tokens: 60,
      completion_tokens: 40,
      cached_tokens: 10,
      total_tokens: 100,
      requests: 2,
    },
    {
      bucket_start: '2026-10-02T00:00:00Z',
      prompt_tokens: 0,
      completion_tokens: 0,
      cached_tokens: 0,
      total_tokens: 0,
      requests: 0,
    },
    {
      bucket_start: '2026-10-03T00:00:00Z',
      prompt_tokens: 30,
      completion_tokens: 20,
      cached_tokens: 5,
      total_tokens: 50,
      requests: 1,
    },
  ],
};

const KEYS = [
  {
    api_key_id: '11111111-1111-4111-8111-111111111111',
    name: 'Production key',
    key_prefix: 'sk-live-1234',
    prompt_tokens: 900_000,
    completion_tokens: 200_000,
    cached_tokens: 90_000,
    total_tokens: 1_100_000,
    requests: 30,
  },
  {
    api_key_id: '22222222-2222-4222-8222-222222222222',
    name: null,
    key_prefix: 'sk-test-5678',
    prompt_tokens: 300_000,
    completion_tokens: 100_000,
    cached_tokens: 10_000,
    total_tokens: 400_000,
    requests: 10,
  },
  {
    api_key_id: '33333333-3333-4333-8333-333333333333',
    name: null,
    key_prefix: null,
    prompt_tokens: 0,
    completion_tokens: 0,
    cached_tokens: 0,
    total_tokens: 0,
    requests: 0,
  },
];

function installUsageMock(overrides: Routes = {}) {
  return installFetchMock({
    '/api/v1/tenants': () =>
      jsonResponse({ items: TENANTS, total: TENANTS.length, limit: 100, offset: 0 }),
    '/api/v1/usage/summary': () => jsonResponse(SUMMARY),
    '/api/v1/usage/series': () => jsonResponse(SERIES),
    '/api/v1/usage/by-key': () => jsonResponse({ limit: 100, items: KEYS }),
    ...overrides,
  });
}

function callsTo(fetchMock: ReturnType<typeof installFetchMock>, path: string) {
  return fetchMock.mock.calls.filter(([input]) => toUrl(input).pathname === path);
}

function lastParams(fetchMock: ReturnType<typeof installFetchMock>, path: string) {
  const calls = callsTo(fetchMock, path);
  const call = calls[calls.length - 1];
  return call === undefined ? null : toUrl(call[0]).searchParams;
}

async function openUsage(user: ReturnType<typeof userEvent.setup>) {
  await connectWithKey(user);
  await user.click(await screen.findByRole('tab', { name: 'Usage' }));
  await screen.findByRole('heading', { name: 'Usage' });
}

describe('usage panel', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(FIXED_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not request usage or tenants until a master key is connected', async () => {
    const fetchMock = installFetchMock();
    const user = userEvent.setup();
    renderApp();

    expect(
      await screen.findByText('Connect a master key to load the registry.'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Usage' }));
    expect(await screen.findByText('Connect a master key to load usage.')).toBeInTheDocument();

    expect(callsTo(fetchMock, '/api/v1/tenants')).toHaveLength(0);
    for (const path of USAGE_PATHS) {
      expect(callsTo(fetchMock, path)).toHaveLength(0);
    }
  });

  it('moves tab focus and selection with ArrowRight, Home, and End', async () => {
    installFetchMock();
    const user = userEvent.setup();
    renderApp();

    const modelsTab = screen.getByRole('tab', { name: 'Models' });
    const usageTab = screen.getByRole('tab', { name: 'Usage' });
    const modelsPanel = document.getElementById('models-panel');
    const usagePanel = document.getElementById('usage-panel');

    expect(modelsPanel).not.toBeNull();
    expect(usagePanel).not.toBeNull();
    expect(modelsTab).toHaveAttribute('aria-selected', 'true');
    expect(usageTab).toHaveAttribute('aria-selected', 'false');
    expect(modelsPanel).not.toHaveAttribute('hidden');
    expect(usagePanel).toHaveAttribute('hidden');

    modelsTab.focus();
    await user.keyboard('{ArrowRight}');

    expect(document.activeElement).toBe(usageTab);
    expect(usageTab).toHaveAttribute('aria-selected', 'true');
    expect(modelsTab).toHaveAttribute('aria-selected', 'false');
    expect(usagePanel).not.toHaveAttribute('hidden');
    expect(modelsPanel).toHaveAttribute('hidden');

    await user.keyboard('{Home}');
    expect(document.activeElement).toBe(modelsTab);
    expect(modelsTab).toHaveAttribute('aria-selected', 'true');
    expect(modelsPanel).not.toHaveAttribute('hidden');
    expect(usagePanel).toHaveAttribute('hidden');

    await user.keyboard('{End}');
    expect(document.activeElement).toBe(usageTab);
    expect(usageTab).toHaveAttribute('aria-selected', 'true');
    expect(usagePanel).not.toHaveAttribute('hidden');
    expect(modelsPanel).toHaveAttribute('hidden');
  });

  it('renders compact totals with exact values and cached as a subset of input', async () => {
    installUsageMock();
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    const totals = await screen.findByRole('region', { name: 'Window totals' });
    expect(within(totals).getByText('1.2M')).toBeInTheDocument();
    expect(within(totals).getByText('1,200,000')).toBeInTheDocument();
    expect(within(totals).getByText('300K')).toBeInTheDocument();
    expect(within(totals).getByText('1.5M')).toBeInTheDocument();
    expect(within(totals).getByText('42')).toBeInTheDocument();
    expect(within(totals).getByText('Cached tokens')).toBeInTheDocument();
    expect(within(totals).getByText('subset of input')).toBeInTheDocument();
  });

  it('renders usage when cached tokens exceed prompt tokens', async () => {
    const oddSummary = {
      ...SUMMARY,
      prompt_tokens: 50_000,
      cached_tokens: 80_000,
    };
    const oddSeries = {
      bucket: 'day',
      points: SERIES.points.map((point) => ({
        ...point,
        prompt_tokens: point.prompt_tokens,
        cached_tokens: point.prompt_tokens + 1_000,
      })),
    };
    const oddKeys = KEYS.map((key) => ({
      ...key,
      cached_tokens: key.prompt_tokens + 1_000,
    }));
    installUsageMock({
      '/api/v1/usage/summary': () => jsonResponse(oddSummary),
      '/api/v1/usage/series': () => jsonResponse(oddSeries),
      '/api/v1/usage/by-key': () => jsonResponse({ limit: 100, items: oddKeys }),
    });
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    const totals = await screen.findByRole('region', { name: 'Window totals' });
    expect(within(totals).getByText('1.5M')).toBeInTheDocument();
    expect(
      await screen.findByRole('list', { name: /Daily total tokens from Oct 1, 2026/ }),
    ).toBeInTheDocument();
    expect(await screen.findByRole('table', { name: 'Usage by API key' })).toBeInTheDocument();
    expect(screen.queryByText('Could not load usage totals')).not.toBeInTheDocument();
    expect(screen.queryByText('Could not load the usage chart')).not.toBeInTheDocument();
    expect(screen.queryByText('Could not load usage by key')).not.toBeInTheDocument();
  });

  it('renders one accessible bar per daily point, including zero-token days', async () => {
    installUsageMock();
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    const chart = await screen.findByRole('list', {
      name: 'Daily total tokens from Oct 1, 2026 to Oct 3, 2026, UTC',
    });
    const bars = within(chart).getAllByRole('listitem');

    expect(bars).toHaveLength(SERIES.points.length);
    expect(bars[0]).toHaveAccessibleName('Oct 1, 2026 UTC: 100 total tokens across 2 requests');
    expect(bars[1]).toHaveAccessibleName('Oct 2, 2026 UTC: 0 total tokens across 0 requests');
    expect(bars[2]).toHaveAccessibleName('Oct 3, 2026 UTC: 50 total tokens across 1 request');
    expect(screen.getByText('Last bar covers today so far (UTC).')).toBeInTheDocument();
  });

  it('keeps every zero-token day as a labeled bar and notes the empty range', async () => {
    const zeroPoints = SERIES.points.map((point) => ({
      ...point,
      prompt_tokens: 0,
      completion_tokens: 0,
      cached_tokens: 0,
      total_tokens: 0,
      requests: 0,
    }));
    installUsageMock({
      '/api/v1/usage/series': () => jsonResponse({ bucket: 'day', points: zeroPoints }),
    });
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    const chart = await screen.findByRole('list', {
      name: 'Daily total tokens from Oct 1, 2026 to Oct 3, 2026, UTC',
    });
    expect(within(chart).getAllByRole('listitem')).toHaveLength(zeroPoints.length);
    expect(screen.getByText('No tokens recorded in this range.')).toBeInTheDocument();
  });

  it('renders a single daily point as one bar whose range starts and ends on that day', async () => {
    const singlePoint = SERIES.points.slice(0, 1);
    installUsageMock({
      '/api/v1/usage/series': () => jsonResponse({ bucket: 'day', points: singlePoint }),
    });
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    const chart = await screen.findByRole('list', {
      name: 'Daily total tokens from Oct 1, 2026 to Oct 1, 2026, UTC',
    });
    expect(within(chart).getAllByRole('listitem')).toHaveLength(1);
  });

  it('floors the since window to UTC midnight and explains the partial final bucket', async () => {
    const fetchMock = installUsageMock();
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    await waitFor(() => {
      expect(lastParams(fetchMock, '/api/v1/usage/summary')?.get('since')).toBe(
        '2026-09-25T00:00:00.000Z',
      );
    });
    expect(await screen.findByText('Last bar covers today so far (UTC).')).toBeInTheDocument();
  });

  it('renders by-key rows with name, prefix, and short-id fallbacks', async () => {
    installUsageMock();
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    const table = await screen.findByRole('table', { name: 'Usage by API key' });
    expect(within(table).getByText('Production key')).toBeInTheDocument();
    expect(within(table).getByText('sk-live-1234')).toBeInTheDocument();
    expect(within(table).getByText('sk-test-5678')).toBeInTheDocument();
    expect(within(table).getByText('33333333…')).toBeInTheDocument();
    expect(within(table).getByText('1,100,000')).toBeInTheDocument();

    for (const label of ['Key', 'Requests', 'Input', 'Output', 'Cached', 'Total']) {
      expect(within(table).getByRole('columnheader', { name: label })).toBeInTheDocument();
    }

    const cards = screen.getByRole('list', { name: 'Usage by API key cards' });
    expect(within(cards).getAllByRole('listitem')).toHaveLength(KEYS.length);
    expect(within(cards).getByText('Production key')).toBeInTheDocument();
  });

  it('shows an empty state when no key usage is recorded', async () => {
    installUsageMock({
      '/api/v1/usage/by-key': () => jsonResponse({ limit: 100, items: [] }),
    });
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    expect(await screen.findByText('No usage in this range')).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Usage by API key' })).not.toBeInTheDocument();
  });

  it('shows the HTTP status, message, code, and request id when by-key usage fails', async () => {
    const fetchMock = installUsageMock({
      '/api/v1/usage/by-key': () =>
        jsonResponse(
          {
            error: {
              message: 'Usage store unavailable',
              type: 'server_error',
              param: null,
              code: 'usage_unavailable',
              request_id: 'req_usage_503',
            },
          },
          503,
          { 'x-request-id': 'req_usage_503' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    expect(await screen.findByText('Could not load usage by key')).toBeInTheDocument();
    expect(screen.getByText('HTTP 503')).toBeInTheDocument();
    expect(screen.getByText('Usage store unavailable')).toBeInTheDocument();
    expect(screen.getByText('usage_unavailable')).toBeInTheDocument();
    expect(screen.getByText('req_usage_503')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry loading usage by key' }));

    await waitFor(() => {
      expect(callsTo(fetchMock, '/api/v1/usage/by-key')).toHaveLength(2);
    });
  });

  it('adds tenant_id to every usage request when a tenant is selected', async () => {
    const fetchMock = installUsageMock();
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);
    const select = await screen.findByLabelText('Tenant');
    await screen.findByRole('option', { name: 'Acme' });
    await user.selectOptions(select, 'tenant-a');

    await waitFor(() => {
      for (const path of USAGE_PATHS) {
        const call = callsTo(fetchMock, path).find(
          ([input]) => toUrl(input).searchParams.get('tenant_id') === 'tenant-a',
        );
        expect(call, `${path} should include tenant_id`).toBeDefined();
      }
    });

    expect(lastParams(fetchMock, '/api/v1/usage/series')?.get('bucket')).toBe('day');
    expect(lastParams(fetchMock, '/api/v1/usage/by-key')?.get('limit')).toBe('100');
  });

  it('sends UTC since values for the default 30-day, 7-day, and 90-day windows without until', async () => {
    const fetchMock = installUsageMock();
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    const assertWindow = async (since: string) => {
      await waitFor(() => {
        for (const path of USAGE_PATHS) {
          const params = lastParams(fetchMock, path);
          expect(params?.get('since'), `${path} should use ${since}`).toBe(since);
          expect(params?.has('until'), `${path} should omit until`).toBe(false);
        }
      });
    };

    await assertWindow('2026-09-25T00:00:00.000Z');

    await user.click(screen.getByRole('button', { name: '7 days' }));
    await assertWindow('2026-10-18T00:00:00.000Z');

    await user.click(screen.getByRole('button', { name: '90 days' }));
    await assertWindow('2026-07-27T00:00:00.000Z');
  });

  it('recomputes the since window from a fresh anchor on refresh', async () => {
    const fetchMock = installUsageMock();
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);
    await screen.findByRole('table', { name: 'Usage by API key' });
    await screen.findByRole('list', { name: /Daily total tokens/ });
    const firstSince = lastParams(fetchMock, '/api/v1/usage/summary')?.get('since');
    expect(firstSince).toBe('2026-09-25T00:00:00.000Z');

    vi.setSystemTime(new Date('2026-11-04T09:15:00.000Z'));
    await user.click(screen.getByRole('button', { name: 'Refresh usage' }));

    await waitFor(() => {
      for (const path of USAGE_PATHS) {
        const nextSince = lastParams(fetchMock, path)?.get('since');
        expect(nextSince, `${path} should use the refreshed window`).toBe(
          '2026-10-05T00:00:00.000Z',
        );
      }
    });

    for (const path of USAGE_PATHS) {
      expect(callsTo(fetchMock, path)).toHaveLength(2);
    }

    const afterSince = lastParams(fetchMock, '/api/v1/usage/summary')?.get('since');
    expect(new Date(afterSince ?? '').getTime()).toBeGreaterThan(
      new Date(firstSince ?? '').getTime(),
    );

    const usageRegion = screen.getByRole('region', { name: 'Usage' });
    expect(await within(usageRegion).findByText('09:15:00 UTC')).toBeInTheDocument();
  });

  it('shows the selected tenant limits as read-only facts', async () => {
    installUsageMock();
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);
    const select = await screen.findByLabelText('Tenant');
    await screen.findByRole('option', { name: 'Acme' });
    await user.selectOptions(select, 'tenant-a');

    const limits = screen.getByRole('group', { name: 'Tenant limits' });
    expect(await within(limits).findByText('1,000,000 tokens/month')).toBeInTheDocument();
    expect(within(limits).getByText('60 req/min')).toBeInTheDocument();
    expect(within(limits).queryByRole('textbox')).not.toBeInTheDocument();
    expect(within(limits).queryByRole('spinbutton')).not.toBeInTheDocument();

    await user.selectOptions(select, 'tenant-b');
    expect(await within(limits).findByText('No limits')).toBeInTheDocument();
  });

  it('refreshes every usage query and shows a UTC last-updated time', async () => {
    const fetchMock = installUsageMock();
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);
    await screen.findByRole('table', { name: 'Usage by API key' });
    await screen.findByRole('list', { name: /Daily total tokens/ });

    const usageRegion = screen.getByRole('region', { name: 'Usage' });
    expect(await within(usageRegion).findByText('12:00:00 UTC')).toBeInTheDocument();

    const before = USAGE_PATHS.map((path) => callsTo(fetchMock, path).length);
    await user.click(screen.getByRole('button', { name: 'Refresh usage' }));

    await waitFor(() => {
      USAGE_PATHS.forEach((path, index) => {
        expect(callsTo(fetchMock, path).length).toBeGreaterThan(before[index] ?? 0);
      });
    });
  });

  it('announces usage updates and refreshes the announcement after the data reloads', async () => {
    installUsageMock();
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    const firstAnnouncement = await screen.findByText(
      'Usage updated at 12:00:00 UTC for the last 30 days.',
    );
    expect(firstAnnouncement).toHaveAttribute('role', 'status');

    vi.setSystemTime(new Date('2026-10-26T08:30:15.000Z'));
    await user.click(screen.getByRole('button', { name: 'Refresh usage' }));

    expect(
      await screen.findByText('Usage updated at 08:30:15 UTC for the last 30 days.'),
    ).toBeInTheDocument();
    expect(
      screen.queryByText('Usage updated at 12:00:00 UTC for the last 30 days.'),
    ).not.toBeInTheDocument();

    const usageRegion = screen.getByRole('region', { name: 'Usage' });
    expect(await within(usageRegion).findByText('08:30:15 UTC')).toBeInTheDocument();
  });

  it('notes when the tenant list is truncated', async () => {
    installUsageMock({
      '/api/v1/tenants': () => jsonResponse({ items: TENANTS, total: 150, limit: 100, offset: 0 }),
    });
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);

    expect(await screen.findByText('Showing 2 of 150 tenants')).toBeInTheDocument();
  });

  it('removes usage data on disconnect, returns to the connect prompt, and keeps storage empty', async () => {
    const fetchMock = installUsageMock();
    const user = userEvent.setup();
    renderApp();

    await openUsage(user);
    expect(await screen.findByText('1.2M')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Usage by API key' })).toBeInTheDocument();

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe('');
    expect(document.body.textContent).not.toContain('mk_test_123');

    const callsBefore = [...USAGE_PATHS, '/api/v1/tenants'].reduce(
      (total, path) => total + callsTo(fetchMock, path).length,
      0,
    );

    await user.click(screen.getByRole('button', { name: 'Disconnect' }));

    expect(await screen.findByText('Connect a master key to load usage.')).toBeInTheDocument();
    expect(screen.queryByText('1.2M')).not.toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Usage by API key' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Tenant')).not.toBeInTheDocument();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);

    const callsAfter = [...USAGE_PATHS, '/api/v1/tenants'].reduce(
      (total, path) => total + callsTo(fetchMock, path).length,
      0,
    );
    expect(callsAfter).toBe(callsBefore);
  });
});
