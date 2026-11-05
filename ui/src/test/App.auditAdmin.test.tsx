import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AuditDeleteResult, TenantSummary } from '../api/client';
import { signIn } from './signIn';
import { installFetchMock, jsonResponse, toUrl, type Routes } from './fetchMock';
import { renderApp } from './renderApp';

const TENANT: TenantSummary = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Acme',
  created_at: '2026-09-01T00:00:00Z',
  monthly_token_quota: null,
  requests_per_minute: null,
  tokens_per_minute: null,
  max_concurrent_requests: null,
  audit_retention_days: null,
  audit_enabled: true,
  model_access_mode: 'all',
  plan_tokens: null,
  plan_allow_overage: false,
  monthly_cost_budget: null,
};

function tenantPage(tenants: TenantSummary[]): Response {
  return jsonResponse({ items: tenants, total: tenants.length, limit: 100, offset: 0 });
}

function installAuditAdminMock(
  overrides: Routes = {},
  sessionOptions: Parameters<typeof installFetchMock>[1] = {},
): ReturnType<typeof installFetchMock> {
  return installFetchMock(
    {
      '/api/v1/tenants': () => tenantPage([TENANT]),
      ...overrides,
    },
    sessionOptions,
  );
}

function exportCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input]) => toUrl(input).pathname === '/api/v1/audit/export');
}

function deleteCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return url.pathname === '/api/v1/audit' && (init?.method ?? 'GET').toUpperCase() === 'DELETE';
  });
}

async function openAuditAdminDialog(user: ReturnType<typeof userEvent.setup>) {
  await signIn(user);
  await user.click(await screen.findByRole('tab', { name: 'Audit' }));
  await screen.findByRole('region', { name: 'Audit' });
  await user.click(screen.getByRole('button', { name: 'Export or delete audit data' }));
  return screen.findByRole('dialog', { name: 'Audit export & retention' });
}

function stubDownload() {
  const createObjectURL = vi.fn(() => 'blob:audit-download');
  const revokeObjectURL = vi.fn();
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = createObjectURL;
  URL.revokeObjectURL = revokeObjectURL;

  let clicked: { href: string; download: string } | null = null;
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked = { href: this.href, download: this.download };
  });

  return {
    createObjectURL,
    revokeObjectURL,
    clicked: () => clicked,
    restore: () => {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    },
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('audit export and delete', () => {
  it('downloads a tenant window from the stream without touching browser storage', async () => {
    const download = stubDownload();
    try {
      const fetchMock = installAuditAdminMock({
        'GET /api/v1/audit/export': () =>
          new Response('{"request_id":"req-1"}\n', {
            status: 200,
            headers: {
              'Content-Type': 'application/x-ndjson',
              'Content-Disposition': 'attachment; filename="audit-acme.csv"',
            },
          }),
      });
      const user = userEvent.setup();
      renderApp();

      const dialog = await openAuditAdminDialog(user);
      await within(dialog).findByRole('option', { name: 'Acme' });
      await user.selectOptions(within(dialog).getByLabelText('Tenant'), TENANT.id);
      fireEvent.change(within(dialog).getByLabelText('From'), {
        target: { value: '2026-10-01T00:00' },
      });
      fireEvent.change(within(dialog).getByLabelText('To'), {
        target: { value: '2026-10-20T00:00' },
      });
      await user.selectOptions(within(dialog).getByLabelText('Format'), 'csv');
      await user.click(within(dialog).getByRole('button', { name: 'Export audit data' }));

      expect(await within(dialog).findByText('Downloaded audit-acme.csv.')).toBeInTheDocument();

      const calls = exportCalls(fetchMock);
      expect(calls).toHaveLength(1);
      const call = calls[0];
      expect(call).toBeDefined();
      if (call === undefined) return;
      const params = toUrl(call[0]).searchParams;
      expect(params.get('tenant_id')).toBe(TENANT.id);
      expect(params.get('format')).toBe('csv');
      expect(params.get('since')).toBe(new Date('2026-10-01T00:00').toISOString());
      expect(params.get('until')).toBe(new Date('2026-10-20T00:00').toISOString());
      expect(call[1]?.credentials).toBe('include');

      expect(download.createObjectURL).toHaveBeenCalledOnce();
      expect(download.revokeObjectURL).toHaveBeenCalledWith('blob:audit-download');
      expect(download.clicked()).toEqual({
        href: 'blob:audit-download',
        download: 'audit-acme.csv',
      });
      expect(localStorage.length).toBe(0);
      expect(sessionStorage.length).toBe(0);
    } finally {
      download.restore();
    }
  });

  it('previews a deletion and only deletes after the second confirmation', async () => {
    const fetchMock = installAuditAdminMock({
      'DELETE /api/v1/audit': (url) => {
        const params = url.searchParams;
        const dryRun = params.get('dry_run') === 'true';
        const result: AuditDeleteResult = {
          tenant_id: TENANT.id,
          before: params.get('before') ?? '',
          dry_run: dryRun,
          requests_deleted: 12,
          sessions_deleted: dryRun ? 0 : 3,
          requests_remaining: dryRun ? 12 : 0,
        };
        return jsonResponse(result);
      },
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openAuditAdminDialog(user);
    await within(dialog).findByRole('option', { name: 'Acme' });
    await user.selectOptions(within(dialog).getByLabelText('Tenant'), TENANT.id);
    fireEvent.change(within(dialog).getByLabelText('Delete requests before'), {
      target: { value: '2026-01-01T00:00' },
    });
    await user.click(within(dialog).getByRole('button', { name: 'Preview deletion' }));

    expect(
      await within(dialog).findByText('Preview only. Nothing has been deleted yet.'),
    ).toBeInTheDocument();
    expect(deleteCalls(fetchMock)).toHaveLength(1);
    const previewCall = deleteCalls(fetchMock)[0];
    expect(previewCall).toBeDefined();
    if (previewCall === undefined) return;
    const previewParams = toUrl(previewCall[0]).searchParams;
    expect(previewParams.get('dry_run')).toBe('true');
    expect(previewParams.get('tenant_id')).toBe(TENANT.id);
    expect(previewParams.get('before')).toBe(new Date('2026-01-01T00:00').toISOString());

    const confirm = within(dialog).getByRole('button', { name: 'Delete audit data permanently' });
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    expect(await within(dialog).findByText('Deletion complete.')).toBeInTheDocument();
    await waitFor(() => {
      expect(deleteCalls(fetchMock)).toHaveLength(2);
    });
    const deleteCall = deleteCalls(fetchMock)[1];
    expect(deleteCall).toBeDefined();
    if (deleteCall === undefined) return;
    expect(toUrl(deleteCall[0]).searchParams.get('dry_run')).toBe('false');

    const status = within(dialog).getByRole('status');
    expect(within(status).getByText('requests_deleted')).toBeInTheDocument();
    expect(within(status).getByText('sessions_deleted')).toBeInTheDocument();
    expect(within(status).getByText('requests_remaining')).toBeInTheDocument();
    expect(within(status).getAllByText('12')).toHaveLength(1);
    expect(within(status).getByText('3')).toBeInTheDocument();

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it('offers export but no deletion controls to an auditor', async () => {
    installAuditAdminMock(
      {},
      { username: 'auditor', password: 'auditor-password', role: 'auditor' },
    );
    const user = userEvent.setup();
    renderApp();

    await signIn(user, { username: 'auditor', password: 'auditor-password' });
    await user.click(await screen.findByRole('tab', { name: 'Audit' }));
    await screen.findByRole('region', { name: 'Audit' });
    await user.click(screen.getByRole('button', { name: 'Export or delete audit data' }));

    const dialog = await screen.findByRole('dialog', { name: 'Audit export & retention' });
    expect(within(dialog).queryByText('Delete (owner only)')).not.toBeInTheDocument();
    expect(
      within(dialog).queryByRole('button', { name: 'Preview deletion' }),
    ).not.toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Export audit data' })).toBeInTheDocument();
  });

  it('shows the status, code, and request id when an export fails', async () => {
    installAuditAdminMock({
      'GET /api/v1/audit/export': () =>
        jsonResponse(
          {
            error: {
              message: 'Audit export is unavailable',
              type: 'server_error',
              param: null,
              code: 'audit_export_unavailable',
              request_id: 'req_audit_export_500',
            },
          },
          500,
          { 'x-request-id': 'req_audit_export_500' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    const dialog = await openAuditAdminDialog(user);
    await within(dialog).findByRole('option', { name: 'Acme' });
    await user.selectOptions(within(dialog).getByLabelText('Tenant'), TENANT.id);
    await user.click(within(dialog).getByRole('button', { name: 'Export audit data' }));

    expect(await within(dialog).findByText('Could not export audit data')).toBeInTheDocument();
    expect(within(dialog).getByText('HTTP 500')).toBeInTheDocument();
    expect(within(dialog).getByText('audit_export_unavailable')).toBeInTheDocument();
    expect(within(dialog).getByText('req_audit_export_500')).toBeInTheDocument();
  });
});
