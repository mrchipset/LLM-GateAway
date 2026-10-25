import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { installFetchMock, jsonResponse } from './fetchMock';
import { renderApp } from './renderApp';

describe('backend health', () => {
  it('shows the backend version and a healthy state when liveness and readiness are ok', async () => {
    installFetchMock();
    renderApp();

    expect(await screen.findByText('v0.1.0')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('Healthy');
    });
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByRole('status')).toHaveTextContent('Liveness and readiness are ok.');
  });

  it('names the failing readiness check when the backend reports degraded readiness', async () => {
    installFetchMock({
      '/readyz': () => jsonResponse({ status: 'unavailable', checks: { database: 'error' } }, 503),
    });
    renderApp();

    expect(await screen.findByText('Readiness degraded')).toBeInTheDocument();

    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('database = error');
    expect(status).not.toHaveTextContent('Healthy');
  });

  it('shows the backend as unreachable and recovers after a retry', async () => {
    installFetchMock({
      '/healthz': () => {
        throw new Error('health unreachable');
      },
      '/readyz': () => {
        throw new Error('readiness unreachable');
      },
    });
    const user = userEvent.setup();
    renderApp();

    expect(await screen.findByText('Backend unreachable')).toBeInTheDocument();

    installFetchMock();
    await user.click(screen.getByRole('button', { name: 'Retry health check' }));

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('Healthy');
    });
  });
});
