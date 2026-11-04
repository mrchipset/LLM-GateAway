import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { AdminSummary, CreateAdminInput, UpdateAdminInput } from '../api/client';
import { DEFAULT_ADMIN_ID, installFetchMock, jsonResponse, toUrl } from './fetchMock';
import { renderApp } from './renderApp';
import { signIn } from './signIn';

const OWNER_ADMIN: AdminSummary = {
  id: DEFAULT_ADMIN_ID,
  username: 'owner',
  display_name: 'Olive Owner',
  role: 'owner',
  active: true,
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-10-20T00:00:00Z',
  last_login_at: '2026-10-24T17:24:00Z',
};

const OPS_ADMIN: AdminSummary = {
  id: '22222222-2222-4222-8222-222222222222',
  username: 'operator',
  display_name: 'Owen Operator',
  role: 'operator',
  active: true,
  created_at: '2026-09-02T00:00:00Z',
  updated_at: '2026-10-21T00:00:00Z',
  last_login_at: null,
};

const NEW_ADMIN: AdminSummary = {
  id: '33333333-3333-4333-8333-333333333333',
  username: 'jane.doe',
  display_name: 'Jane Doe',
  role: 'auditor',
  active: true,
  created_at: '2026-10-25T12:00:00Z',
  updated_at: '2026-10-25T12:00:00Z',
  last_login_at: null,
};

const NEW_PASSWORD = 'a-very-long-password';

function adminListResponse(admins: AdminSummary[], url: URL) {
  const limit = Number(url.searchParams.get('limit') ?? '50');
  const offset = Number(url.searchParams.get('offset') ?? '0');
  return jsonResponse({
    items: admins.slice(offset, offset + limit),
    total: admins.length,
    limit,
    offset,
  });
}

function installAdminsMock(
  overrides: Parameters<typeof installFetchMock>[0] = {},
  initial: AdminSummary[] = [OWNER_ADMIN, OPS_ADMIN],
) {
  let admins = initial;
  const fetchMock = installFetchMock({
    '/api/v1/admins': (url) => adminListResponse(admins, url),
    'POST /api/v1/admins': (_url, init) => {
      const body = JSON.parse(String(init.body)) as CreateAdminInput;
      if (admins.some((admin) => admin.username === body.username)) {
        return jsonResponse(
          {
            error: {
              message: `Admin '${body.username}' already exists`,
              type: 'invalid_request_error',
              param: 'username',
              code: 'duplicate_admin',
              request_id: 'req_duplicate_admin',
            },
          },
          409,
          { 'x-request-id': 'req_duplicate_admin' },
        );
      }
      const created: AdminSummary = {
        ...NEW_ADMIN,
        username: body.username,
        display_name: body.display_name,
        role: body.role,
      };
      admins = [...admins, created];
      return jsonResponse(created, 201);
    },
    'PATCH /api/v1/admins/:id': (url, init) => {
      const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
      const body = JSON.parse(String(init.body)) as UpdateAdminInput;
      const existing = admins.find((admin) => admin.id === id);
      if (existing === undefined) {
        return jsonResponse(
          {
            error: {
              message: 'Admin was not found',
              type: 'invalid_request_error',
              param: null,
              code: 'admin_not_found',
              request_id: 'req_admin_missing',
            },
          },
          404,
        );
      }
      const updated: AdminSummary = {
        ...existing,
        display_name: body.display_name ?? existing.display_name,
        role: body.role ?? existing.role,
        active: body.active ?? existing.active,
      };
      admins = admins.map((admin) => (admin.id === id ? updated : admin));
      return jsonResponse(updated);
    },
    ...overrides,
  });
  return { fetchMock, admins: () => admins };
}

function patchCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return url.pathname.startsWith('/api/v1/admins/') && init?.method === 'PATCH';
  });
}

function postCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return url.pathname === '/api/v1/admins' && init?.method === 'POST';
  });
}

async function openAdmins(user: ReturnType<typeof userEvent.setup>) {
  await signIn(user);
  await user.click(await screen.findByRole('tab', { name: 'Admins' }));
  return screen.findByRole('table', { name: 'Admins' });
}

describe('admin management', () => {
  it('lists admins with role, active state, and last sign-in', async () => {
    installAdminsMock();
    const user = userEvent.setup();
    renderApp();

    const table = await openAdmins(user);

    const ownerRow = within(table).getByRole('row', { name: /Olive Owner/ });
    expect(within(ownerRow).getByText('Owner')).toBeInTheDocument();
    expect(within(ownerRow).getByText('Active')).toBeInTheDocument();
    expect(within(ownerRow).getByText('Oct 24, 2026, 17:24 UTC')).toBeInTheDocument();

    const operatorRow = within(table).getByRole('row', { name: /Owen Operator/ });
    expect(within(operatorRow).getByText('Operator')).toBeInTheDocument();
    expect(within(operatorRow).getByText('Never')).toBeInTheDocument();
    expect(screen.getByText('2 admins')).toBeInTheDocument();
  });

  it('creates an admin and never renders the password afterwards', async () => {
    const { fetchMock } = installAdminsMock();
    const user = userEvent.setup();
    renderApp();

    await openAdmins(user);
    await user.click(screen.getByRole('button', { name: 'Create admin' }));
    const dialog = await screen.findByRole('dialog', { name: 'Create admin' });

    await user.type(within(dialog).getByLabelText('Username'), 'jane.doe');
    await user.type(within(dialog).getByLabelText('Display name'), 'Jane Doe');
    await user.selectOptions(within(dialog).getByLabelText('Role'), 'auditor');
    await user.type(within(dialog).getByLabelText('Password'), NEW_PASSWORD);
    await user.click(within(dialog).getByRole('button', { name: 'Create admin' }));

    expect(await screen.findByText("Admin 'jane.doe' created.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    const calls = postCalls(fetchMock);
    expect(calls).toHaveLength(1);
    const body = JSON.parse(String(calls[0]?.[1]?.body)) as CreateAdminInput;
    expect(body).toEqual({
      username: 'jane.doe',
      display_name: 'Jane Doe',
      role: 'auditor',
      password: NEW_PASSWORD,
    });

    expect(document.body.textContent).not.toContain(NEW_PASSWORD);
    expect(await screen.findByText('3 admins')).toBeInTheDocument();
    const updatedTable = await screen.findByRole('table', { name: 'Admins' });
    expect(within(updatedTable).getByText('jane.doe')).toBeInTheDocument();
  });

  it('blocks a short password inline before sending anything', async () => {
    const { fetchMock } = installAdminsMock();
    const user = userEvent.setup();
    renderApp();

    await openAdmins(user);
    await user.click(screen.getByRole('button', { name: 'Create admin' }));
    const dialog = await screen.findByRole('dialog', { name: 'Create admin' });

    await user.type(within(dialog).getByLabelText('Username'), 'jane.doe');
    await user.type(within(dialog).getByLabelText('Display name'), 'Jane Doe');
    await user.type(within(dialog).getByLabelText('Password'), 'too-short');
    await user.click(within(dialog).getByRole('button', { name: 'Create admin' }));

    expect(within(dialog).getByText('Use at least 12 characters.')).toBeInTheDocument();
    expect(postCalls(fetchMock)).toHaveLength(0);
    expect(screen.getByRole('dialog', { name: 'Create admin' })).toBeInTheDocument();
  });

  it('surfaces duplicate_admin with code and request id', async () => {
    installAdminsMock();
    const user = userEvent.setup();
    renderApp();

    await openAdmins(user);
    await user.click(screen.getByRole('button', { name: 'Create admin' }));
    const dialog = await screen.findByRole('dialog', { name: 'Create admin' });

    await user.type(within(dialog).getByLabelText('Username'), 'operator');
    await user.type(within(dialog).getByLabelText('Display name'), 'Another Operator');
    await user.type(within(dialog).getByLabelText('Password'), NEW_PASSWORD);
    await user.click(within(dialog).getByRole('button', { name: 'Create admin' }));

    expect(await within(dialog).findByText('Could not create admin')).toBeInTheDocument();
    expect(within(dialog).getByText('HTTP 409')).toBeInTheDocument();
    expect(within(dialog).getByText("Admin 'operator' already exists")).toBeInTheDocument();
    expect(within(dialog).getByText('duplicate_admin')).toBeInTheDocument();
    expect(within(dialog).getByText('req_duplicate_admin')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Username')).toHaveValue('operator');
  });

  it('changes a role and shows the updated badge', async () => {
    const { fetchMock } = installAdminsMock();
    const user = userEvent.setup();
    renderApp();

    const table = await openAdmins(user);
    await user.click(within(table).getByRole('button', { name: 'Edit operator' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit admin' });

    await user.selectOptions(within(dialog).getByLabelText('Role'), 'auditor');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByText("Admin 'operator' updated.")).toBeInTheDocument();
    const calls = patchCalls(fetchMock);
    expect(calls).toHaveLength(1);
    expect(JSON.parse(String(calls[0]?.[1]?.body))).toEqual({ role: 'auditor' });

    const updatedTable = await screen.findByRole('table', { name: 'Admins' });
    const row = within(updatedTable).getByRole('row', { name: /Owen Operator/ });
    expect(within(row).getByText('Auditor')).toBeInTheDocument();
  });

  it('requires a confirmation before deactivating an admin', async () => {
    const { fetchMock } = installAdminsMock();
    const user = userEvent.setup();
    renderApp();

    const table = await openAdmins(user);
    await user.click(within(table).getByRole('button', { name: 'Edit operator' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit admin' });

    const activeSwitch = within(dialog).getByRole('switch', { name: 'Active' });
    expect(activeSwitch).toHaveAttribute('aria-checked', 'true');
    await user.click(activeSwitch);
    expect(activeSwitch).toHaveAttribute('aria-checked', 'false');

    const save = within(dialog).getByRole('button', { name: 'Save changes' });
    expect(save).toBeDisabled();
    await user.click(
      within(dialog).getByRole('checkbox', {
        name: 'I understand this admin will be signed out.',
      }),
    );
    expect(save).toBeEnabled();
    await user.click(save);

    expect(await screen.findByText("Admin 'operator' updated.")).toBeInTheDocument();
    const calls = patchCalls(fetchMock);
    expect(JSON.parse(String(calls[0]?.[1]?.body))).toEqual({ active: false });

    const updatedTable = await screen.findByRole('table', { name: 'Admins' });
    const row = within(updatedTable).getByRole('row', { name: /Owen Operator/ });
    expect(within(row).getByText('Inactive')).toBeInTheDocument();
  });

  it('shows last_owner_required when the final owner would lose the role', async () => {
    installAdminsMock({
      'PATCH /api/v1/admins/:id': () =>
        jsonResponse(
          {
            error: {
              message: 'At least one active owner must remain',
              type: 'invalid_request_error',
              param: null,
              code: 'last_owner_required',
              request_id: 'req_last_owner',
            },
          },
          409,
          { 'x-request-id': 'req_last_owner' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    await openAdmins(user);
    const table = await screen.findByRole('table', { name: 'Admins' });
    await user.click(within(table).getByRole('button', { name: 'Edit owner' }));
    const dialog = await screen.findByRole('dialog', { name: 'Edit admin' });

    await user.selectOptions(within(dialog).getByLabelText('Role'), 'operator');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));

    expect(await within(dialog).findByText('At least one active owner must remain')).toBeVisible();
    expect(within(dialog).getByText('last_owner_required')).toBeInTheDocument();
    expect(within(dialog).getByText('req_last_owner')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Edit admin' })).toBeInTheDocument();
  });

  it('resets a password only after confirmation and keeps it out of the DOM', async () => {
    const { fetchMock } = installAdminsMock();
    const user = userEvent.setup();
    renderApp();

    const table = await openAdmins(user);
    await user.click(within(table).getByRole('button', { name: 'Reset password for operator' }));
    const dialog = await screen.findByRole('dialog', { name: 'Reset password' });

    await user.type(within(dialog).getByLabelText('New password'), NEW_PASSWORD);
    await user.type(within(dialog).getByLabelText('Confirm password'), 'different-password');
    await user.click(within(dialog).getByRole('button', { name: 'Reset password' }));
    expect(within(dialog).getByText('Passwords do not match.')).toBeInTheDocument();
    expect(patchCalls(fetchMock)).toHaveLength(0);

    await user.clear(within(dialog).getByLabelText('Confirm password'));
    await user.type(within(dialog).getByLabelText('Confirm password'), NEW_PASSWORD);
    await user.click(within(dialog).getByRole('button', { name: 'Reset password' }));

    expect(
      await screen.findByText('Password reset for operator. Their sessions were revoked.'),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    const calls = patchCalls(fetchMock);
    expect(calls).toHaveLength(1);
    expect(JSON.parse(String(calls[0]?.[1]?.body))).toEqual({ password: NEW_PASSWORD });
    expect(document.body.textContent).not.toContain(NEW_PASSWORD);
  });
});
