import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { AdminAuditEvent } from '../api/client';
import { installFetchMock, jsonResponse, toUrl } from './fetchMock';
import { renderApp } from './renderApp';
import { signIn } from './signIn';

const ROLE_EVENT: AdminAuditEvent = {
  id: 'eeeeeeee-1111-4111-8111-111111111111',
  actor_type: 'admin',
  actor_id: 'aaaaaaaa-1111-4111-8111-111111111111',
  actor_name: 'olive',
  action: 'admin.updated',
  target_type: 'admin',
  target_id: '22222222-2222-4222-8222-222222222222',
  before: { role: 'operator', active: true },
  after: { role: 'auditor', active: false },
  request_id: 'req_admin_role',
  created_at: '2026-10-25T12:00:00Z',
};

const TENANT_EVENT: AdminAuditEvent = {
  id: 'eeeeeeee-2222-4222-8222-222222222222',
  actor_type: 'master',
  actor_id: null,
  actor_name: 'master-key',
  action: 'tenant.created',
  target_type: 'tenant',
  target_id: '11111111-1111-4111-8111-111111111111',
  before: null,
  after: { name: 'Acme', monthly_token_quota: 1_000_000, password: 'never-show-this' },
  request_id: 'req_tenant_create',
  created_at: '2026-10-24T09:30:00Z',
};

function auditPage(events: AdminAuditEvent[], url: URL) {
  const limit = Number(url.searchParams.get('limit') ?? '25');
  const offset = Number(url.searchParams.get('offset') ?? '0');
  return jsonResponse({
    items: events.slice(offset, offset + limit),
    total: events.length,
    limit,
    offset,
  });
}

function auditCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input]) => toUrl(input).pathname === '/api/v1/admin-audit');
}

function lastAuditParams(fetchMock: ReturnType<typeof installFetchMock>) {
  const calls = auditCalls(fetchMock);
  const last = calls[calls.length - 1];
  return last === undefined ? null : toUrl(last[0]).searchParams;
}

async function openAdminAudit(user: ReturnType<typeof userEvent.setup>) {
  await signIn(user);
  await user.click(await screen.findByRole('tab', { name: 'Admin audit' }));
  return screen.findByRole('region', { name: 'Admin audit' });
}

describe('admin audit', () => {
  it('refetches when the panel is reopened so new events appear', async () => {
    let events = [ROLE_EVENT];
    const fetchMock = installFetchMock({
      '/api/v1/admin-audit': (url) => auditPage(events, url),
    });
    const user = userEvent.setup();
    renderApp();

    const region = await openAdminAudit(user);
    const table = await within(region).findByRole('table', { name: 'Admin audit events' });
    await within(table).findByText('admin.updated');

    events = [ROLE_EVENT, TENANT_EVENT];
    await user.click(screen.getByRole('tab', { name: 'Models' }));
    await user.click(screen.getByRole('tab', { name: 'Admin audit' }));

    const reopened = await screen.findByRole('region', { name: 'Admin audit' });
    const reopenedTable = await within(reopened).findByRole('table', {
      name: 'Admin audit events',
    });
    await within(reopenedTable).findByText('tenant.created');
    expect(auditCalls(fetchMock)).toHaveLength(2);
  });

  it('renders actor, action, target, and a compact before/after view', async () => {
    installFetchMock({
      '/api/v1/admin-audit': (url) => auditPage([ROLE_EVENT, TENANT_EVENT], url),
    });
    const user = userEvent.setup();
    renderApp();

    const region = await openAdminAudit(user);
    const table = await within(region).findByRole('table', { name: 'Admin audit events' });

    const roleRow = within(table).getByRole('row', { name: /admin\.updated/ });
    expect(within(roleRow).getByText('olive')).toBeInTheDocument();
    expect(within(roleRow).getByText('Admin')).toBeInTheDocument();
    expect(within(roleRow).getByText('admin.updated')).toBeInTheDocument();
    expect(roleRow.textContent).toContain('role: operator → auditor');
    expect(roleRow.textContent).toContain('active: yes → no');
    expect(within(roleRow).getByText('Oct 25, 2026, 12:00 UTC')).toBeInTheDocument();

    const tenantRow = within(table).getByRole('row', { name: /tenant\.created/ });
    expect(within(tenantRow).getByText('master-key')).toBeInTheDocument();
    expect(within(tenantRow).getByText('Master key')).toBeInTheDocument();
    expect(tenantRow.textContent).toContain('name = Acme');
    expect(tenantRow.textContent).toContain('monthly_token_quota = 1000000');
  });

  it('never renders fields or values that look like secrets', async () => {
    installFetchMock({
      '/api/v1/admin-audit': (url) =>
        auditPage(
          [
            {
              ...ROLE_EVENT,
              before: { role: 'owner', password: 'never-show-this', session_token: 'tok_live_1' },
              after: { role: 'operator', password: 'also-secret', api_key: 'lgw_live_secret' },
            },
          ],
          url,
        ),
    });
    const user = userEvent.setup();
    renderApp();

    const region = await openAdminAudit(user);
    const table = await within(region).findByRole('table', { name: 'Admin audit events' });
    const row = within(table).getByRole('row', { name: /admin\.updated/ });

    expect(row.textContent).toContain('role: owner → operator');
    expect(row.textContent).not.toContain('never-show-this');
    expect(row.textContent).not.toContain('also-secret');
    expect(row.textContent).not.toContain('tok_live_1');
    expect(row.textContent).not.toContain('lgw_live_secret');
    expect(document.body.textContent).not.toContain('never-show-this');
    expect(document.body.textContent).not.toContain('lgw_live_secret');
  });

  it('sends actor, action, target, and time filters as query params', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/admin-audit': (url) => auditPage([ROLE_EVENT], url),
    });
    const user = userEvent.setup();
    renderApp();

    const region = await openAdminAudit(user);
    await within(region).findByRole('table', { name: 'Admin audit events' });

    await user.type(within(region).getByLabelText('Action'), 'admin.updated');
    await user.selectOptions(within(region).getByLabelText('Target type'), 'admin');
    await user.type(within(region).getByLabelText('Target ID'), ROLE_EVENT.target_id);
    await user.type(within(region).getByLabelText('Actor ID'), ROLE_EVENT.actor_id ?? '');
    fireEvent.change(within(region).getByLabelText('Since'), {
      target: { value: '2026-10-01T10:00' },
    });
    fireEvent.change(within(region).getByLabelText('Until'), {
      target: { value: '2026-10-02T10:00' },
    });
    await user.click(within(region).getByRole('button', { name: 'Apply filters' }));

    await waitFor(() => {
      const params = lastAuditParams(fetchMock);
      expect(params?.get('action')).toBe('admin.updated');
      expect(params?.get('target_type')).toBe('admin');
      expect(params?.get('target_id')).toBe(ROLE_EVENT.target_id);
      expect(params?.get('actor_id')).toBe(ROLE_EVENT.actor_id);
      expect(params?.get('since')).toBe(new Date('2026-10-01T10:00').toISOString());
      expect(params?.get('until')).toBe(new Date('2026-10-02T10:00').toISOString());
      expect(params?.get('offset')).toBe('0');
      expect(params?.get('limit')).toBe('25');
    });
  });

  it('rejects an inverted time range before sending it', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/admin-audit': (url) => auditPage([ROLE_EVENT], url),
    });
    const user = userEvent.setup();
    renderApp();

    const region = await openAdminAudit(user);
    await within(region).findByRole('table', { name: 'Admin audit events' });
    const callsBefore = auditCalls(fetchMock).length;

    fireEvent.change(within(region).getByLabelText('Since'), {
      target: { value: '2026-10-03T10:00' },
    });
    fireEvent.change(within(region).getByLabelText('Until'), {
      target: { value: '2026-10-02T10:00' },
    });
    await user.click(within(region).getByRole('button', { name: 'Apply filters' }));

    expect(within(region).getByText('Since must be before until.')).toBeInTheDocument();
    expect(auditCalls(fetchMock)).toHaveLength(callsBefore);
  });

  it('marks an inverted time range invalid and moves focus to the field', async () => {
    installFetchMock({
      '/api/v1/admin-audit': (url) => auditPage([ROLE_EVENT], url),
    });
    const user = userEvent.setup();
    renderApp();

    const region = await openAdminAudit(user);
    await within(region).findByRole('table', { name: 'Admin audit events' });

    const since = within(region).getByLabelText('Since');
    const until = within(region).getByLabelText('Until');
    fireEvent.change(since, { target: { value: '2026-10-03T10:00' } });
    fireEvent.change(until, { target: { value: '2026-10-02T10:00' } });
    await user.click(within(region).getByRole('button', { name: 'Apply filters' }));

    expect(within(region).getByRole('alert')).toHaveTextContent('Since must be before until.');
    expect(until).toHaveAttribute('aria-invalid', 'true');
    expect(since).toHaveAttribute('aria-invalid', 'false');
    expect(document.activeElement).toBe(until);
  });

  it('paginates through events', async () => {
    const events: AdminAuditEvent[] = Array.from({ length: 60 }, (_, index) => ({
      ...ROLE_EVENT,
      id: `event-${String(index + 1).padStart(4, '0')}`,
      action: `admin.updated`,
      created_at: '2026-10-25T12:00:00Z',
    }));
    const fetchMock = installFetchMock({
      '/api/v1/admin-audit': (url) => auditPage(events, url),
    });
    const user = userEvent.setup();
    renderApp();

    const region = await openAdminAudit(user);
    await within(region).findByRole('table', { name: 'Admin audit events' });
    await within(region).findByText('Showing 1–25 of 60');

    await user.click(within(region).getByRole('button', { name: 'Next admin audit page' }));

    await waitFor(() => {
      expect(lastAuditParams(fetchMock)?.get('offset')).toBe('25');
    });
    await within(region).findByText('Showing 26–50 of 60');
  });

  it('renders the empty state when nothing matches', async () => {
    installFetchMock();
    const user = userEvent.setup();
    renderApp();

    const region = await openAdminAudit(user);
    expect(await within(region).findByText('No admin events')).toBeInTheDocument();
    expect(within(region).getByText(/Management actions will appear here/)).toBeInTheDocument();
  });

  it('shows the error code and request id when the list fails', async () => {
    installFetchMock({
      '/api/v1/admin-audit': () =>
        jsonResponse(
          {
            error: {
              message: 'The admin audit store is unavailable',
              type: 'server_error',
              param: null,
              code: 'admin_audit_unavailable',
              request_id: 'req_admin_audit_failed',
            },
          },
          500,
          { 'x-request-id': 'req_admin_audit_failed' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    const region = await openAdminAudit(user);
    expect(
      await within(region).findByText('Could not load the admin audit trail'),
    ).toBeInTheDocument();
    expect(within(region).getByText('HTTP 500')).toBeInTheDocument();
    expect(within(region).getByText('admin_audit_unavailable')).toBeInTheDocument();
    expect(within(region).getByText('req_admin_audit_failed')).toBeInTheDocument();
  });
});
