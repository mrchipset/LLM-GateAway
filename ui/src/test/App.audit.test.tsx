import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  ApiKeySummary,
  AuditDiff,
  AuditSessionSummary,
  TenantLimitsPatch,
  TenantSummary,
} from '../api/client';
import { connectWithKey } from './connectWithKey';
import { installFetchMock, jsonResponse, toUrl, type Routes } from './fetchMock';
import { renderApp } from './renderApp';

const FIXED_NOW = new Date('2026-10-25T12:00:00.000Z');

const ACME: TenantSummary = {
  id: 'aaaaaaaa-1111-4111-8111-111111111111',
  name: 'Acme',
  created_at: '2026-09-01T00:00:00Z',
  monthly_token_quota: 1_000_000,
  requests_per_minute: 60,
  audit_enabled: true,
};

const SOLO: TenantSummary = {
  id: 'bbbbbbbb-2222-4222-8222-222222222222',
  name: 'Solo',
  created_at: '2026-09-02T00:00:00Z',
  monthly_token_quota: null,
  requests_per_minute: null,
  audit_enabled: false,
};

const TENANTS = [ACME, SOLO];

const MODEL = {
  id: 'gpt-4o-mini',
  provider: 'openai',
  upstream_model: 'gpt-4o-mini-2024-07-18',
  enabled: true,
  created_at: '2026-09-01T00:00:00Z',
};

const MODELS = [
  MODEL,
  {
    id: 'claude-haiku',
    provider: 'anthropic',
    upstream_model: 'claude-3-5-haiku',
    enabled: true,
    created_at: '2026-09-02T00:00:00Z',
  },
];

const PRODUCTION_KEY: ApiKeySummary = {
  id: 'cccccccc-1111-4111-8111-111111111111',
  tenant_id: ACME.id,
  name: 'Production',
  key_prefix: 'lgw_live_prod',
  created_at: '2026-10-01T08:15:00Z',
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
};

const BATCH_KEY: ApiKeySummary = {
  id: 'cccccccc-2222-4222-8222-222222222222',
  tenant_id: ACME.id,
  name: 'Batch',
  key_prefix: 'lgw_live_batch',
  created_at: '2026-10-02T08:15:00Z',
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
};

const KEYS = [PRODUCTION_KEY, BATCH_KEY];

const SESSION_ID = 'dddddddd-1111-4111-8111-111111111111';
const REQUEST_ONE = 'req-root-0001';
const REQUEST_TWO = 'req-edit-0002';

const SESSION: AuditSessionSummary = {
  id: SESSION_ID,
  tenant_id: ACME.id,
  external_session_id: 'ext-support-42',
  api_key_id: PRODUCTION_KEY.id,
  api_key_prefix: PRODUCTION_KEY.key_prefix,
  model_id: MODEL.id,
  provider: MODEL.provider,
  title_preview: 'Refund policy walkthrough',
  created_at: '2026-10-24T10:00:00Z',
  last_seen_at: '2026-10-25T11:00:00Z',
  request_count: 2,
  total_tokens: 1234,
};

const ROOT_MESSAGES = [
  { role: 'system', content: 'You are a support agent.' },
  { role: 'user', content: 'Full root prompt: my order arrived damaged.' },
];

function responseChange(overrides: Record<string, unknown> = {}) {
  return {
    content_changed: true,
    previous_content_hash: null,
    content_hash: 'hash-1',
    finish_reason_changed: false,
    previous_finish_reason: null,
    finish_reason: 'stop',
    tool_calls_added: 0,
    tool_calls_removed: 0,
    tool_call_names: [],
    ...overrides,
  };
}

function rootDiff(includeContent: boolean): AuditDiff {
  return {
    change_type: 'new_session',
    common_prefix: 0,
    added_messages: [
      { index: 0, role: 'system', hash: 'h0', preview: 'You are a support agent.' },
      { index: 1, role: 'user', hash: 'h1', preview: 'My order arrived damaged.' },
    ],
    modified_messages: [],
    removed_messages: [],
    parameter_changes: includeContent
      ? { model: { kind: 'values', from: null, to: MODEL.id } }
      : {
          model: {
            kind: 'hashes',
            from_hash: 'a'.repeat(64),
            to_hash: 'b'.repeat(64),
          },
        },
    usage_delta: {
      prompt_tokens: 120,
      completion_tokens: 40,
      cached_tokens: 0,
      total_tokens: 160,
    },
    response_change: {
      content_changed: true,
      previous_content_hash: null,
      content_hash: 'hash-1',
      finish_reason_changed: false,
      previous_finish_reason: null,
      finish_reason: 'stop',
      tool_calls_added: 0,
      tool_calls_removed: 0,
      tool_call_names: [],
    },
  };
}

function editDiff(includeContent: boolean): AuditDiff {
  const toolsHashes = {
    kind: 'hashes' as const,
    from_hash: 'f'.repeat(64),
    to_hash: 'e'.repeat(64),
  };
  return {
    change_type: 'edit',
    common_prefix: 2,
    added_messages: [
      { index: 3, role: 'user', hash: 'h3', preview: 'Please check the second item.' },
    ],
    modified_messages: [
      {
        index: 2,
        role: 'assistant',
        before_hash: 'h2a',
        after_hash: 'h2b',
        before_preview: 'The refund is 10%.',
        after_preview: 'The refund is 25%.',
      },
    ],
    removed_messages: [{ index: 4, role: 'tool', hash: 'h4', preview: 'old tool output' }],
    parameter_changes: includeContent
      ? {
          temperature: { kind: 'values', from: 0.2, to: 0.9 },
          tools: toolsHashes,
        }
      : {
          temperature: {
            kind: 'hashes',
            from_hash: 'c'.repeat(64),
            to_hash: 'd'.repeat(64),
          },
          tools: toolsHashes,
        },
    usage_delta: {
      prompt_tokens: 10,
      completion_tokens: -5,
      cached_tokens: 5,
      total_tokens: 5,
    },
    response_change: {
      content_changed: true,
      previous_content_hash: 'hash-1',
      content_hash: 'hash-2',
      finish_reason_changed: true,
      previous_finish_reason: 'stop',
      finish_reason: 'length',
      tool_calls_added: 1,
      tool_calls_removed: 1,
      tool_call_names: ['lookup_order'],
    },
  };
}

const EDIT_MESSAGES = [
  ...ROOT_MESSAGES,
  { role: 'assistant', content: 'The refund is 10%.' },
  { role: 'user', content: 'Full second prompt: please check the second item.' },
];

const TOOL_CALLS = [
  { id: 'call_1', type: 'function', function: { name: 'lookup_order', arguments: '{}' } },
];

function sessionTurns(includeContent: boolean) {
  return [
    {
      request_id: REQUEST_ONE,
      parent_request_id: null,
      turn_index: 0,
      match_method: 'new',
      change_type: 'new_session',
      model_id: MODEL.id,
      provider: MODEL.provider,
      is_stream: true,
      status: 'completed',
      finish_reason: 'stop',
      truncated: false,
      created_at: '2026-10-24T10:00:00Z',
      prompt_tokens: 120,
      completion_tokens: 40,
      cached_tokens: 0,
      total_tokens: 160,
      request_message_count: 2,
      diff: rootDiff(includeContent),
      request_messages: includeContent ? ROOT_MESSAGES : null,
      request_params: includeContent ? { model: MODEL.id, temperature: 0.2 } : null,
      response_content: includeContent ? 'Full root response: I can help with that.' : null,
      response_tool_calls: includeContent ? [] : null,
    },
    {
      request_id: REQUEST_TWO,
      parent_request_id: REQUEST_ONE,
      turn_index: 1,
      match_method: 'prefix',
      change_type: 'edit',
      model_id: MODEL.id,
      provider: MODEL.provider,
      is_stream: false,
      status: 'upstream_error',
      finish_reason: 'length',
      truncated: true,
      created_at: '2026-10-25T11:00:00Z',
      prompt_tokens: 130,
      completion_tokens: 35,
      cached_tokens: 5,
      total_tokens: 165,
      request_message_count: 4,
      diff: editDiff(includeContent),
      request_messages: includeContent ? EDIT_MESSAGES : null,
      request_params: includeContent ? { model: MODEL.id, temperature: 0.9 } : null,
      response_content: includeContent ? 'Full edited response.' : null,
      response_tool_calls: includeContent ? TOOL_CALLS : null,
    },
  ];
}

function sessionDetail(includeContent: boolean) {
  return { session: SESSION, turns: sessionTurns(includeContent) };
}

const REQUEST_DETAIL = {
  request: {
    request_id: REQUEST_ONE,
    session_id: SESSION_ID,
    tenant_id: ACME.id,
    api_key_id: PRODUCTION_KEY.id,
    parent_request_id: null,
    turn_index: 0,
    match_method: 'new',
    change_type: 'new_session',
    model_id: MODEL.id,
    provider: MODEL.provider,
    is_stream: true,
    status: 'completed',
    finish_reason: 'stop',
    truncated: false,
    created_at: '2026-10-24T10:00:00Z',
    prompt_tokens: 120,
    completion_tokens: 40,
    cached_tokens: 0,
    total_tokens: 160,
    request_messages: ROOT_MESSAGES,
    request_params: { model: MODEL.id, temperature: 0.1 },
    response_content: 'Full root response: I can help with that.',
    response_tool_calls: [],
    response_content_hash: 'hash-1',
  },
  diff: {
    ...rootDiff(true),
    parameter_changes: {
      temperature: { kind: 'values', from: 0.1, to: 0.7 },
      tools: {
        kind: 'hashes',
        from_hash: 'f'.repeat(64),
        to_hash: 'e'.repeat(64),
      },
    },
    response_change: responseChange(),
  },
  truncated: false,
};

function apiError(status: number, code: string, message: string, requestId: string): Response {
  return jsonResponse(
    {
      error: {
        message,
        type: 'invalid_request_error',
        param: null,
        code,
        request_id: requestId,
      },
    },
    status,
    { 'x-request-id': requestId },
  );
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

function keyPage(keys: ApiKeySummary[], url: URL): Response {
  const limit = Number(url.searchParams.get('limit') ?? '100');
  const offset = Number(url.searchParams.get('offset') ?? '0');
  const tenantId = url.searchParams.get('tenant_id');
  const filtered = tenantId === null ? keys : keys.filter((key) => key.tenant_id === tenantId);
  return jsonResponse({
    items: filtered.slice(offset, offset + limit),
    total: filtered.length,
    limit,
    offset,
    tenant_id: tenantId,
  });
}

function sessionsPage(sessions: AuditSessionSummary[], url: URL): Response {
  const limit = Number(url.searchParams.get('limit') ?? '20');
  const offset = Number(url.searchParams.get('offset') ?? '0');
  const tenantId = url.searchParams.get('tenant_id');
  const filtered =
    tenantId === null ? sessions : sessions.filter((session) => session.tenant_id === tenantId);
  return jsonResponse({
    items: filtered.slice(offset, offset + limit),
    total: filtered.length,
    limit,
    offset,
  });
}

function installAuditMock(overrides: Routes = {}) {
  return installFetchMock({
    '/api/v1/tenants': (url) => tenantPage(TENANTS, url),
    '/api/v1/models': () =>
      jsonResponse({ items: MODELS, total: MODELS.length, limit: 100, offset: 0 }),
    '/api/v1/keys': (url) => keyPage(KEYS, url),
    '/api/v1/audit/sessions': (url) => sessionsPage([SESSION], url),
    'GET /api/v1/audit/sessions/:id': (url) =>
      jsonResponse(sessionDetail(url.searchParams.get('include_content') === 'true')),
    'GET /api/v1/audit/requests/:id': () => jsonResponse(REQUEST_DETAIL),
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

function sessionDetailCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input]) =>
    toUrl(input).pathname.startsWith('/api/v1/audit/sessions/'),
  );
}

function lastSessionParams(fetchMock: ReturnType<typeof installFetchMock>) {
  const calls = sessionDetailCalls(fetchMock);
  const call = calls[calls.length - 1];
  return call === undefined ? null : toUrl(call[0]).searchParams;
}

function requestDetailCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input]) =>
    toUrl(input).pathname.startsWith('/api/v1/audit/requests/'),
  );
}

function auditRegion() {
  return screen.getByRole('region', { name: 'Audit' });
}

async function openAudit(user: ReturnType<typeof userEvent.setup>) {
  await connectWithKey(user);
  await user.click(await screen.findByRole('tab', { name: 'Audit' }));
  await screen.findByRole('heading', { name: 'Audit' });
}

async function openSession(user: ReturnType<typeof userEvent.setup>) {
  const region = auditRegion();
  const table = await within(region).findByRole('table', { name: 'Audited sessions' });
  await user.click(
    within(table).getByRole('button', { name: 'Open session Refund policy walkthrough' }),
  );
  await within(region).findByRole('heading', { name: 'Refund policy walkthrough' });
}

describe('audit console', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(FIXED_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not request audit data before a master key is connected', async () => {
    const fetchMock = installAuditMock();
    const user = userEvent.setup();
    renderApp();

    await user.click(screen.getByRole('tab', { name: 'Audit' }));

    expect(
      await screen.findByText('Connect a master key to view the audit log.'),
    ).toBeInTheDocument();
    expect(callsTo(fetchMock, '/api/v1/audit/sessions')).toHaveLength(0);
    expect(sessionDetailCalls(fetchMock)).toHaveLength(0);
    expect(requestDetailCalls(fetchMock)).toHaveLength(0);
  });

  it('loads the default 30-day window with master-key auth and renders session metadata', async () => {
    const fetchMock = installAuditMock();
    const user = userEvent.setup();
    renderApp();

    await openAudit(user);

    const region = auditRegion();
    const table = await within(region).findByRole('table', { name: 'Audited sessions' });
    const params = lastParams(fetchMock, '/api/v1/audit/sessions');
    expect(params?.get('since')).toBe('2026-09-25T00:00:00.000Z');
    expect(params?.get('limit')).toBe('20');
    expect(params?.get('offset')).toBe('0');
    expect(params?.has('tenant_id')).toBe(false);
    expect(params?.has('until')).toBe(false);

    const listCall = callsTo(fetchMock, '/api/v1/audit/sessions')[0];
    expect(listCall).toBeDefined();
    if (listCall !== undefined) {
      expect(new Headers(listCall[1]?.headers).get('Authorization')).toBe('Bearer mk_test_123');
    }

    const row = within(table).getByRole('row', { name: /Refund policy walkthrough/ });
    expect(within(row).getByText('Acme')).toBeInTheDocument();
    expect(within(row).getByText('aaaaaaaa…')).toBeInTheDocument();
    expect(within(row).getByText('lgw_live_prod')).toBeInTheDocument();
    expect(within(row).getByText('gpt-4o-mini')).toBeInTheDocument();
    expect(within(row).getByText('2')).toBeInTheDocument();
    expect(within(row).getByTitle('Oct 25, 2026, 11:00 UTC')).toBeInTheDocument();
    expect(within(row).getByTitle('1,234 tokens')).toBeInTheDocument();
    expect(within(region).getByText('1 session')).toBeInTheDocument();
  });

  it('sends tenant, key, model, search, and UTC range filters', async () => {
    const fetchMock = installAuditMock();
    const user = userEvent.setup();
    renderApp();

    await openAudit(user);
    const region = auditRegion();
    await within(region).findByRole('table', { name: 'Audited sessions' });

    const tenantSelect = within(region).getByLabelText('Audit tenant');
    await within(region).findByRole('option', { name: 'Acme' });
    await user.selectOptions(tenantSelect, ACME.id);

    await waitFor(() => {
      expect(lastParams(fetchMock, '/api/v1/audit/sessions')?.get('tenant_id')).toBe(ACME.id);
    });
    await waitFor(() => {
      expect(lastParams(fetchMock, '/api/v1/keys')?.get('tenant_id')).toBe(ACME.id);
      expect(lastParams(fetchMock, '/api/v1/keys')?.get('limit')).toBe('100');
    });

    const keySelect = within(region).getByLabelText('API key');
    await within(region).findByRole('option', { name: 'Production · lgw_live_prod' });
    await user.selectOptions(keySelect, PRODUCTION_KEY.id);
    await waitFor(() => {
      expect(lastParams(fetchMock, '/api/v1/audit/sessions')?.get('api_key_id')).toBe(
        PRODUCTION_KEY.id,
      );
    });

    const modelSelect = within(region).getByLabelText('Model');
    await within(region).findByRole('option', { name: 'gpt-4o-mini' });
    await user.selectOptions(modelSelect, MODEL.id);
    await waitFor(() => {
      expect(lastParams(fetchMock, '/api/v1/audit/sessions')?.get('model_id')).toBe(MODEL.id);
    });

    await user.type(within(region).getByLabelText('Search'), 'refund');
    await user.click(within(region).getByRole('button', { name: 'Search' }));
    await waitFor(() => {
      expect(lastParams(fetchMock, '/api/v1/audit/sessions')?.get('q')).toBe('refund');
    });

    await user.click(within(region).getByRole('button', { name: '7 days' }));
    await waitFor(() => {
      expect(lastParams(fetchMock, '/api/v1/audit/sessions')?.get('since')).toBe(
        '2026-10-18T00:00:00.000Z',
      );
    });

    await user.click(within(region).getByRole('button', { name: '90 days' }));
    await waitFor(() => {
      expect(lastParams(fetchMock, '/api/v1/audit/sessions')?.get('since')).toBe(
        '2026-07-27T00:00:00.000Z',
      );
    });
  });

  it('paginates audited sessions in pages of 20', async () => {
    const manySessions = Array.from({ length: 25 }, (_, index) => ({
      ...SESSION,
      id: `eeeeeeee-${String(index + 1).padStart(4, '0')}-4111-8111-111111111111`,
      title_preview: `Session ${String(index + 1).padStart(2, '0')}`,
    }));
    const fetchMock = installAuditMock({
      '/api/v1/audit/sessions': (url) => sessionsPage(manySessions, url),
    });
    const user = userEvent.setup();
    renderApp();

    await openAudit(user);
    const region = auditRegion();
    expect(await within(region).findByText('25 sessions')).toBeInTheDocument();

    let table = await within(region).findByRole('table', { name: 'Audited sessions' });
    expect(within(table).getAllByRole('rowheader')).toHaveLength(20);
    expect(within(region).getByText('Showing 1–20 of 25')).toBeInTheDocument();

    await user.click(within(region).getByRole('button', { name: 'Next audit page' }));

    expect(await within(region).findByText('Showing 21–25 of 25')).toBeInTheDocument();
    table = await within(region).findByRole('table', { name: 'Audited sessions' });
    expect(within(table).getAllByRole('rowheader')).toHaveLength(5);
    expect(within(table).getByText('Session 25')).toBeInTheDocument();
    expect(within(region).getByRole('button', { name: 'Next audit page' })).toBeDisabled();

    const offsets = callsTo(fetchMock, '/api/v1/audit/sessions').map(
      ([input]) => toUrl(input).searchParams.get('offset') ?? '',
    );
    expect(offsets).toEqual(['0', '20']);
  });

  it('shows a skeleton while sessions load', async () => {
    let resolvePage: (response: Response) => void = () => {};
    const pendingPage = new Promise<Response>((resolve) => {
      resolvePage = resolve;
    });
    installAuditMock({ '/api/v1/audit/sessions': () => pendingPage });
    const user = userEvent.setup();
    renderApp();

    await openAudit(user);

    const region = auditRegion();
    expect(await within(region).findByText('Loading audited sessions…')).toBeInTheDocument();

    await act(async () => {
      resolvePage(jsonResponse({ items: [SESSION], total: 1, limit: 20, offset: 0 }));
    });

    expect(
      await within(region).findByRole('table', { name: 'Audited sessions' }),
    ).toBeInTheDocument();
  });

  it('shows an empty state when nothing was captured', async () => {
    installAuditMock({
      '/api/v1/audit/sessions': (url) => sessionsPage([], url),
    });
    const user = userEvent.setup();
    renderApp();

    await openAudit(user);

    const region = auditRegion();
    expect(await within(region).findByText('0 sessions')).toBeInTheDocument();
    expect(within(region).getByText('No audited sessions')).toBeInTheDocument();
    expect(
      within(region).queryByRole('table', { name: 'Audited sessions' }),
    ).not.toBeInTheDocument();
  });

  it('shows status, code, and request id when sessions fail and retries', async () => {
    let requests = 0;
    installAuditMock({
      '/api/v1/audit/sessions': () => {
        requests += 1;
        return apiError(500, 'audit_store_unavailable', 'Audit store unavailable', 'req_audit_500');
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openAudit(user);

    const region = auditRegion();
    expect(await within(region).findByText('Could not load audit sessions')).toBeInTheDocument();
    expect(within(region).getByText('HTTP 500')).toBeInTheDocument();
    expect(within(region).getByText('Audit store unavailable')).toBeInTheDocument();
    expect(within(region).getByText('audit_store_unavailable')).toBeInTheDocument();
    expect(within(region).getByText('req_audit_500')).toBeInTheDocument();

    const before = requests;
    await user.click(within(region).getByRole('button', { name: 'Retry loading audit sessions' }));
    await waitFor(() => {
      expect(requests).toBeGreaterThan(before);
    });
  });

  it('opens a session timeline with change badges, diff previews, hashes, deltas, and truncation', async () => {
    const fetchMock = installAuditMock();
    const user = userEvent.setup();
    renderApp();

    await openAudit(user);
    await openSession(user);

    const region = auditRegion();
    expect(lastSessionParams(fetchMock)?.has('include_content')).toBe(false);
    expect(within(region).getByText('Acme')).toBeInTheDocument();
    expect(within(region).getByText('lgw_live_prod')).toBeInTheDocument();
    expect(within(region).getByText(/external: ext-support-42/)).toBeInTheDocument();
    expect(within(region).getByText('2 turns')).toBeInTheDocument();

    expect(within(region).getByText('New session')).toBeInTheDocument();
    expect(within(region).getByText('Edit')).toBeInTheDocument();
    expect(within(region).getByText('Completed')).toBeInTheDocument();
    expect(within(region).getByText('Upstream error')).toBeInTheDocument();
    expect(within(region).getByText('Match: New')).toBeInTheDocument();
    expect(within(region).getByText('Match: Prefix')).toBeInTheDocument();

    expect(within(region).getByText('My order arrived damaged.')).toBeInTheDocument();
    expect(within(region).getByText('The refund is 10%. → The refund is 25%.')).toBeInTheDocument();
    expect(within(region).getByText('old tool output')).toBeInTheDocument();
    expect(within(region).getAllByText('bounded').length).toBeGreaterThan(0);
    expect(
      within(region).getAllByTitle(
        'Values are shown as hashes while full content is off. Turn on Show full content to load plaintext; values over the capture cap stay hashed.',
      ).length,
    ).toBeGreaterThan(0);
    expect(within(region).getByText('bbbbbbbbbb…')).toBeInTheDocument();
    expect(within(region).getByText('-5')).toBeInTheDocument();
    expect(within(region).getByText('stop → length')).toBeInTheDocument();
    expect(within(region).getByText('lookup_order')).toBeInTheDocument();
    expect(
      within(region).getByText(/Capture truncated this turn at write time/),
    ).toBeInTheDocument();
    expect(within(region).queryByText(/Full root prompt/)).not.toBeInTheDocument();

    await user.click(within(region).getByRole('button', { name: 'Back to all sessions' }));
    const directoryTable = await within(region).findByRole('table', {
      name: 'Audited sessions',
    });
    const rowButton = within(directoryTable).getByRole('button', {
      name: 'Open session Refund policy walkthrough',
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(rowButton);
    });
    expect(
      within(region).queryByRole('heading', { name: 'Refund policy walkthrough' }),
    ).not.toBeInTheDocument();
  });

  it('focuses the session directory heading when the originating row is gone', async () => {
    installAuditMock();
    const { queryClient } = renderApp();
    const user = userEvent.setup();

    await openAudit(user);
    await openSession(user);

    const region = auditRegion();
    const listQueries = queryClient
      .getQueryCache()
      .getAll()
      .filter((query) => String(query.queryKey[0]) === 'audit-sessions');
    expect(listQueries.length).toBeGreaterThan(0);

    await act(async () => {
      for (const query of listQueries) {
        query.setData({ items: [], total: 0, limit: 20, offset: 0 });
      }
    });

    await user.click(within(region).getByRole('button', { name: 'Back to all sessions' }));
    const heading = await within(region).findByRole('heading', { name: 'Session directory' });
    await waitFor(() => {
      expect(document.activeElement).toBe(heading);
    });
  });

  it('fetches full content on demand and never writes it to browser storage or the URL', async () => {
    const fetchMock = installAuditMock();
    const { queryClient } = renderApp();
    const user = userEvent.setup();

    await openAudit(user);
    await openSession(user);

    const region = auditRegion();
    expect(lastSessionParams(fetchMock)?.has('include_content')).toBe(false);
    const toggle = within(region).getByRole('switch', { name: 'Show full content' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    await waitFor(() => {
      expect(lastSessionParams(fetchMock)?.get('include_content')).toBe('true');
    });

    expect(
      await within(region).findAllByText('Full root prompt: my order arrived damaged.'),
    ).toHaveLength(2);
    expect(
      within(region).getByText('Full root response: I can help with that.'),
    ).toBeInTheDocument();
    expect(
      within(region).getAllByTitle('Bounded at capture; this value exceeded the content budget.')
        .length,
    ).toBeGreaterThan(0);
    expect(
      within(region).queryByTitle(
        'Values are shown as hashes while full content is off. Turn on Show full content to load plaintext; values over the capture cap stay hashed.',
      ),
    ).not.toBeInTheDocument();
    expect(within(region).getAllByText('Request parameters').length).toBeGreaterThan(0);
    expect(within(region).getByText(/"temperature": 0\.2/)).toBeInTheDocument();
    expect(within(region).getByText('0.9')).toBeInTheDocument();
    expect(within(region).getByText('Response tool calls · 1')).toBeInTheDocument();
    expect(within(region).getAllByText('lookup_order').length).toBeGreaterThan(0);

    const sessionQueries = queryClient
      .getQueryCache()
      .getAll()
      .filter((query) => String(query.queryKey[0]) === 'audit-session');
    expect(sessionQueries.some((query) => query.queryKey[2] === true)).toBe(true);
    expect(sessionQueries.some((query) => query.queryKey[2] === false)).toBe(true);

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe('');
    expect(window.location.href).not.toContain(REQUEST_ONE);
    expect(window.location.href).not.toContain(SESSION_ID);
    expect(window.location.href).not.toContain('Full root prompt');

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    await waitFor(() => {
      expect(lastSessionParams(fetchMock)?.has('include_content')).toBe(false);
    });
    expect(
      within(region).queryByText('Full root prompt: my order arrived damaged.'),
    ).not.toBeInTheDocument();
  });

  it('explains a 413, hides content, and falls back to per-request detail', async () => {
    const fetchMock = installAuditMock({
      'GET /api/v1/audit/sessions/:id': (url) =>
        url.searchParams.get('include_content') === 'true'
          ? apiError(
              413,
              'audit_content_too_large',
              'Audit content exceeds the configured size limit',
              'req_audit_413',
            )
          : jsonResponse(sessionDetail(false)),
    });
    const user = userEvent.setup();
    renderApp();

    await openAudit(user);
    await openSession(user);

    const region = auditRegion();
    await user.click(within(region).getByRole('switch', { name: 'Show full content' }));

    expect(await within(region).findByText('Session content is too large')).toBeInTheDocument();
    expect(within(region).getByText('HTTP 413')).toBeInTheDocument();
    expect(within(region).getByText('audit_content_too_large')).toBeInTheDocument();
    expect(within(region).getByText('req_audit_413')).toBeInTheDocument();
    expect(within(region).getByText(/Hide full content to load the timeline/)).toBeInTheDocument();

    await user.click(within(region).getByRole('button', { name: 'Hide full content' }));
    expect(await within(region).findByRole('list', { name: 'Session turns' })).toBeInTheDocument();

    await user.click(within(region).getByRole('button', { name: `Open request ${REQUEST_ONE}` }));

    expect(await within(region).findByText('Request detail')).toBeInTheDocument();
    expect(
      within(region).getByText('Full root prompt: my order arrived damaged.'),
    ).toBeInTheDocument();
    expect(
      within(region).getByText('Full root response: I can help with that.'),
    ).toBeInTheDocument();
    expect(requestDetailCalls(fetchMock)).toHaveLength(1);
  });

  it('explains metadata-mode 413 without offering to hide content', async () => {
    installAuditMock({
      'GET /api/v1/audit/sessions/:id': () =>
        apiError(
          413,
          'audit_content_too_large',
          'Audit content exceeds the configured size limit',
          'req_audit_413_metadata',
        ),
    });
    const user = userEvent.setup();
    renderApp();

    await openAudit(user);
    await openSession(user);

    const region = auditRegion();
    expect(await within(region).findByText('Session metadata is too large')).toBeInTheDocument();
    expect(within(region).getByText('HTTP 413')).toBeInTheDocument();
    expect(within(region).getByText('req_audit_413_metadata')).toBeInTheDocument();
    expect(
      within(region).getByText(
        'This session exceeds the response size limit and cannot be partially rendered here. Use the request endpoint with a request id, or raise GATEWAY_AUDIT_MAX_CONTENT_BYTES and restart the gateway.',
      ),
    ).toBeInTheDocument();
    expect(
      within(region).queryByRole('button', { name: 'Hide full content' }),
    ).not.toBeInTheDocument();
    expect(within(region).getByRole('button', { name: 'Back to sessions' })).toBeInTheDocument();

    await user.click(within(region).getByRole('button', { name: 'Back to sessions' }));
    const table = await within(region).findByRole('table', { name: 'Audited sessions' });
    const rowButton = within(table).getByRole('button', {
      name: 'Open session Refund policy walkthrough',
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(rowButton);
    });
  });

  it('shows an inline notice when the selected tenant has audit collection off', async () => {
    const fetchMock = installAuditMock();
    const user = userEvent.setup();
    renderApp();

    await openAudit(user);
    const region = auditRegion();
    await within(region).findByRole('table', { name: 'Audited sessions' });

    await within(region).findByRole('option', { name: 'Solo' });
    await user.selectOptions(within(region).getByLabelText('Audit tenant'), SOLO.id);

    expect(await within(region).findByText(/Audit collection is off for Solo/)).toBeInTheDocument();
    expect(within(region).getByText(/Access → Tenants/)).toBeInTheDocument();
    expect(within(region).queryByRole('button', { name: /enable audit/i })).not.toBeInTheDocument();
    expect(lastParams(fetchMock, '/api/v1/audit/sessions')?.get('tenant_id')).toBe(SOLO.id);
  });

  it('clears every audit cache prefix on disconnect', async () => {
    installAuditMock();
    const { queryClient } = renderApp();
    const user = userEvent.setup();

    await openAudit(user);
    await openSession(user);

    const region = auditRegion();
    await user.click(within(region).getByRole('button', { name: `Open request ${REQUEST_ONE}` }));
    expect(await within(region).findByText('Request detail')).toBeInTheDocument();

    const auditPrefixes = ['audit-sessions', 'audit-session', 'audit-request'];
    const before = queryClient
      .getQueryCache()
      .getAll()
      .filter((query) => auditPrefixes.includes(String(query.queryKey[0])));
    expect(before.length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Disconnect' }));

    expect(
      await screen.findByText('Connect a master key to view the audit log.'),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: 'Refund policy walkthrough' }),
    ).not.toBeInTheDocument();

    await waitFor(() => {
      const remaining = queryClient
        .getQueryCache()
        .getAll()
        .filter((query) => auditPrefixes.includes(String(query.queryKey[0])));
      expect(remaining).toHaveLength(0);
    });
  });

  it('patches the tenant audit toggle and reflects it in the tenant table', async () => {
    let tenants = [{ ...ACME, audit_enabled: false }, SOLO];
    const patchBodies: TenantLimitsPatch[] = [];
    installAuditMock({
      '/api/v1/tenants': (url) => tenantPage(tenants, url),
      'PATCH /api/v1/tenants/:id': (url, init) => {
        const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
        const body = JSON.parse(String(init.body)) as TenantLimitsPatch;
        patchBodies.push(body);
        const existing = tenants.find((tenant) => tenant.id === id);
        if (existing === undefined) {
          return apiError(404, 'tenant_not_found', 'Tenant not found', 'req_missing_tenant');
        }
        const updated = { ...existing, ...body };
        tenants = tenants.map((tenant) => (tenant.id === id ? updated : tenant));
        return jsonResponse(updated);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await connectWithKey(user);
    await user.click(await screen.findByRole('tab', { name: 'Access' }));
    const region = screen.getByRole('region', { name: 'Tenants' });
    const table = await within(region).findByRole('table', { name: 'Tenants' });

    await user.click(within(table).getByRole('button', { name: 'Edit limits for Acme' }));
    let dialog = await screen.findByRole('dialog', { name: 'Edit tenant limits' });
    const toggle = within(dialog).getByRole('switch', { name: 'Audit collection' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([{ audit_enabled: true }]);
    expect(
      await within(region).findByText('Audit collection updated for Acme.'),
    ).toBeInTheDocument();

    const updatedTable = await within(region).findByRole('table', { name: 'Tenants' });
    const updatedRow = within(updatedTable).getByRole('row', { name: /Acme/ });
    expect(within(updatedRow).getByText('On')).toBeInTheDocument();

    await user.click(within(updatedTable).getByRole('button', { name: 'Edit limits for Acme' }));
    dialog = await screen.findByRole('dialog', { name: 'Edit tenant limits' });
    const reopenedToggle = within(dialog).getByRole('switch', { name: 'Audit collection' });
    expect(reopenedToggle).toHaveAttribute('aria-checked', 'true');
    await user.click(reopenedToggle);
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(patchBodies).toEqual([{ audit_enabled: true }, { audit_enabled: false }]);

    const finalTable = await within(region).findByRole('table', { name: 'Tenants' });
    const finalRow = within(finalTable).getByRole('row', { name: /Acme/ });
    expect(within(finalRow).getByText('Off')).toBeInTheDocument();
  });
});
