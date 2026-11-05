import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import type { CreateModelInput, ModelSummary } from '../api/client';
import {
  DEFAULT_ADMIN_PASSWORD,
  DEFAULT_ADMIN_USERNAME,
  installFetchMock,
  jsonResponse,
  toUrl,
} from './fetchMock';
import { renderApp } from './renderApp';
import { signIn } from './signIn';

const CHAT: ModelSummary = {
  id: 'chat-prod',
  provider: 'openai',
  upstream_model: 'gpt-4o-mini',
  enabled: true,
  created_at: '2026-10-24T17:24:00Z',
};

function modelPayload(items: ModelSummary[]) {
  return { items, total: items.length, limit: 100, offset: 0 };
}

function callsTo(fetchMock: ReturnType<typeof installFetchMock>, path: string) {
  return fetchMock.mock.calls.filter(([input]) => toUrl(input).pathname === path);
}

function loginScreen() {
  return screen.findByRole('heading', { name: 'Sign in' });
}

describe('admin session', () => {
  it('starts on the login form and does not load admin data before sign-in', async () => {
    const fetchMock = installFetchMock();
    renderApp();

    await loginScreen();
    expect(screen.getByLabelText('Username')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password');
    expect(callsTo(fetchMock, '/api/v1/models')).toHaveLength(0);
    expect(callsTo(fetchMock, '/api/v1/auth/me')).toHaveLength(1);
  });

  it('signs in, renders the workspace, and shows the signed-in role', async () => {
    const fetchMock = installFetchMock();
    const user = userEvent.setup();
    renderApp();

    await signIn(user);

    expect(await screen.findByRole('tab', { name: 'Models' })).toBeInTheDocument();
    expect(screen.getByText('Signed in')).toBeInTheDocument();
    expect(screen.getByText(DEFAULT_ADMIN_USERNAME)).toBeInTheDocument();
    expect(screen.getByText('Owner')).toBeInTheDocument();

    const loginCall = callsTo(fetchMock, '/api/v1/auth/login')[0];
    expect(loginCall).toBeDefined();
    const [, init] = loginCall ?? [];
    expect(init?.credentials).toBe('include');
    expect(JSON.parse(String(init?.body))).toEqual({
      username: DEFAULT_ADMIN_USERNAME,
      password: DEFAULT_ADMIN_PASSWORD,
    });

    const modelCall = callsTo(fetchMock, '/api/v1/models')[0];
    expect(modelCall).toBeDefined();
    expect(modelCall?.[1]?.credentials).toBe('include');
    expect(new Headers(modelCall?.[1]?.headers).get('Authorization')).toBeNull();
    expect(callsTo(fetchMock, '/api/v1/auth/me')).toHaveLength(2);
    expect(document.cookie).not.toContain('gw_admin_session');
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it('shows invalid_credentials instead of entering the workspace on a wrong password', async () => {
    installFetchMock();
    const user = userEvent.setup();
    renderApp();

    await loginScreen();
    await user.type(screen.getByLabelText('Username'), DEFAULT_ADMIN_USERNAME);
    await user.type(screen.getByLabelText('Password'), 'not-the-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Could not sign in')).toBeInTheDocument();
    expect(screen.getByText('invalid_credentials')).toBeInTheDocument();
    expect(screen.getByText('Invalid username or password')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Models' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Username')).toHaveValue(DEFAULT_ADMIN_USERNAME);
  });

  it('sends the readable CSRF cookie on unsafe requests', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload([CHAT])),
      'POST /api/v1/models': (_url, init) => {
        const body = JSON.parse(String(init.body)) as CreateModelInput;
        return jsonResponse({ ...body, created_at: '2026-10-25T12:00:00Z' }, 201);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await signIn(user);
    await user.click(screen.getByRole('button', { name: 'Register model' }));
    const dialog = await screen.findByRole('dialog', { name: 'Register model' });
    await user.type(within(dialog).getByLabelText('Model id'), 'new-model');
    await user.type(within(dialog).getByLabelText('Upstream model'), 'upstream-model');
    await user.click(within(dialog).getByRole('button', { name: 'Register model' }));

    await screen.findByText("Model 'new-model' registered.");
    const post = fetchMock.mock.calls.find(([input, init]) => {
      const url = toUrl(input);
      return url.pathname === '/api/v1/models' && init?.method === 'POST';
    });
    expect(post).toBeDefined();
    const csrfCookie = document.cookie
      .split(';')
      .map((chunk) => chunk.trim())
      .find((chunk) => chunk.startsWith('gw_admin_csrf='));
    expect(csrfCookie).toBeDefined();
    expect(new Headers(post?.[1]?.headers).get('x-csrf-token')).toBe(csrfCookie?.split('=')[1]);
  });

  it('returns to the login screen with a session expired notice on a 401', async () => {
    let reject = false;
    installFetchMock({
      '/api/v1/models': () => {
        if (reject) {
          return jsonResponse(
            {
              error: {
                message: 'The admin session is invalid or expired',
                type: 'authentication_error',
                param: null,
                code: 'admin_auth_required',
                request_id: 'req_expired',
              },
            },
            401,
            { 'x-request-id': 'req_expired' },
          );
        }
        return jsonResponse(modelPayload([CHAT]));
      },
    });
    const user = userEvent.setup();
    renderApp();

    await signIn(user);
    expect(await screen.findByRole('table', { name: 'Registered models' })).toBeInTheDocument();

    reject = true;
    await user.click(screen.getByRole('button', { name: 'Refresh models' }));

    await loginScreen();
    expect(await screen.findByText('Your session expired. Sign in again.')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Models' })).not.toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Registered models' })).not.toBeInTheDocument();
  });

  it('signs out from the header, clears admin caches, and keeps storage empty', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload([CHAT])),
    });
    const { queryClient } = renderApp();
    const user = userEvent.setup();

    await signIn(user);
    await screen.findByRole('table', { name: 'Registered models' });

    await user.click(screen.getByRole('button', { name: 'Sign out' }));

    await loginScreen();
    expect(await screen.findByText('You have been signed out.')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Models' })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByLabelText('Username'));

    await waitFor(() => {
      const remaining = queryClient
        .getQueryCache()
        .getAll()
        .filter((query) => {
          const key = String(query.queryKey[0]);
          return key.startsWith('admin-') && key !== 'admin-session';
        });
      expect(remaining).toHaveLength(0);
    });

    const logoutCall = callsTo(fetchMock, '/api/v1/auth/logout')[0];
    expect(logoutCall).toBeDefined();
    expect(logoutCall?.[1]?.credentials).toBe('include');
    expect(new Headers(logoutCall?.[1]?.headers).get('x-csrf-token')).not.toBeNull();

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).not.toContain('gw_admin_session');
    expect(document.cookie).not.toContain(DEFAULT_ADMIN_PASSWORD);
    expect(document.body.textContent).not.toContain(DEFAULT_ADMIN_PASSWORD);
  });
});

describe('single sign-on', () => {
  afterEach(() => {
    window.history.replaceState({}, '', '/');
  });

  it('offers SSO when the backend reports it enabled and keeps the password form', async () => {
    installFetchMock({
      '/api/v1/auth/oidc/status': () => jsonResponse({ enabled: true }),
    });
    renderApp();

    const link = await screen.findByRole('link', { name: 'Sign in with SSO' });
    expect(link).toHaveAttribute('href', '/api/v1/auth/oidc/start');
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password');
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('hides SSO when the backend reports it disabled', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/auth/oidc/status': () => jsonResponse({ enabled: false }),
    });
    renderApp();

    await loginScreen();
    await waitFor(() => {
      expect(callsTo(fetchMock, '/api/v1/auth/oidc/status')).toHaveLength(1);
    });
    expect(screen.queryByRole('link', { name: 'Sign in with SSO' })).not.toBeInTheDocument();
  });

  it('hides SSO and still signs in with a password when the status probe fails', async () => {
    installFetchMock({
      '/api/v1/auth/oidc/status': () =>
        jsonResponse(
          {
            error: {
              message: 'OIDC status is unavailable',
              type: 'server_error',
              param: null,
              code: 'internal_error',
              request_id: 'req_oidc_status',
            },
          },
          500,
        ),
    });
    const user = userEvent.setup();
    renderApp();

    await loginScreen();
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Sign in with SSO' })).not.toBeInTheDocument();

    await signIn(user);
    expect(await screen.findByRole('tab', { name: 'Models' })).toBeInTheDocument();
  });

  it('explains a failed SSO sign-in and clears the error code from the URL', async () => {
    installFetchMock();
    window.history.replaceState({}, '', '/?sso_error=role_not_mapped');
    renderApp();

    expect(
      await screen.findByText(
        'Your sign-in role does not grant access to the console. Ask an owner to check the role mapping.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Single sign-on failed');
    await waitFor(() => {
      expect(window.location.search).toBe('');
    });
  });

  it('falls back to a generic message for an unknown SSO error code', async () => {
    installFetchMock();
    window.history.replaceState({}, '', '/?sso_error=a_new_provider_failure');
    renderApp();

    expect(
      await screen.findByText(
        'Single sign-on could not be completed. Try again, or sign in with your password.',
      ),
    ).toBeInTheDocument();
  });
});
