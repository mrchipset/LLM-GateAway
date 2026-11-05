import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { CreateModelInput, ModelSummary } from '../api/client';
import { signIn } from './signIn';
import { installFetchMock, readTestCsrfToken, jsonResponse, toUrl } from './fetchMock';
import { renderApp } from './renderApp';

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

function modelPayload(items: ModelSummary[], total = items.length) {
  return { items, total, limit: 100, offset: 0 };
}

function modelCalls(fetchMock: ReturnType<typeof installFetchMock>, method: string) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return url.pathname === '/api/v1/models' && (init?.method ?? 'GET').toUpperCase() === method;
  });
}

function deleteModelCalls(fetchMock: ReturnType<typeof installFetchMock>) {
  return fetchMock.mock.calls.filter(([input, init]) => {
    const url = toUrl(input);
    return (
      url.pathname.startsWith('/api/v1/models/') &&
      (init?.method ?? 'GET').toUpperCase() === 'DELETE'
    );
  });
}

async function openRegistry(user: ReturnType<typeof userEvent.setup>) {
  await signIn(user);
  return screen.findByRole('table', { name: 'Registered models' });
}

async function openRegisterDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Register model' }));
  return screen.findByRole('dialog', { name: 'Register model' });
}

describe('model registration', () => {
  it('registers a model with the entered values and refreshes the list', async () => {
    let models = [CHAT];
    const fetchMock = installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload(models)),
      'POST /api/v1/models': (_url, init) => {
        const body = JSON.parse(String(init.body)) as CreateModelInput;
        const created: ModelSummary = { ...body, created_at: '2026-10-25T12:00:00Z' };
        models = [...models, created];
        return jsonResponse(created, 201);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openRegistry(user);
    const dialog = await openRegisterDialog(user);

    await user.type(within(dialog).getByLabelText('Model id'), 'deepseek-chat');
    await user.selectOptions(within(dialog).getByLabelText('Provider'), 'deepseek');
    await user.type(within(dialog).getByLabelText('Upstream model'), '  deepseek-chat-v3  ');
    await user.click(within(dialog).getByRole('button', { name: 'Register model' }));

    expect(await screen.findByText("Model 'deepseek-chat' registered.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    const postCalls = modelCalls(fetchMock, 'POST');
    expect(postCalls).toHaveLength(1);
    const call = postCalls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;
    const [, init] = call;
    expect(JSON.parse(String(init?.body))).toEqual({
      id: 'deepseek-chat',
      provider: 'deepseek',
      upstream_model: 'deepseek-chat-v3',
      enabled: true,
      supports_tools: true,
      supports_streaming: true,
    });
    expect(new Headers(init?.headers).get('x-csrf-token')).toBe(readTestCsrfToken());

    const table = await screen.findByRole('table', { name: 'Registered models' });
    expect(within(table).getByText('deepseek-chat')).toBeInTheDocument();
    expect(await screen.findByText('2 models')).toBeInTheDocument();
  });

  it('sends enabled false when the model is registered disabled', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload([CHAT])),
      'POST /api/v1/models': (_url, init) => {
        const body = JSON.parse(String(init.body)) as CreateModelInput;
        return jsonResponse({ ...body, created_at: '2026-10-25T12:00:00Z' }, 201);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openRegistry(user);
    const dialog = await openRegisterDialog(user);

    await user.type(within(dialog).getByLabelText('Model id'), 'staged-model');
    await user.type(within(dialog).getByLabelText('Upstream model'), 'staged-upstream');
    await user.click(within(dialog).getByRole('switch', { name: 'Enabled' }));
    await user.click(within(dialog).getByRole('button', { name: 'Register model' }));

    await screen.findByText("Model 'staged-model' registered.");
    const postCalls = modelCalls(fetchMock, 'POST');
    expect(postCalls).toHaveLength(1);
    const call = postCalls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({ enabled: false });
  });

  it('sends filled capabilities and leaves unfilled numbers out of the payload', async () => {
    const posted: CreateModelInput[] = [];
    let models = [CHAT];
    installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload(models)),
      'POST /api/v1/models': (_url, init) => {
        const body = JSON.parse(String(init.body)) as CreateModelInput;
        posted.push(body);
        const created: ModelSummary = { ...body, created_at: '2026-10-25T12:00:00Z' };
        models = [...models, created];
        return jsonResponse(created, 201);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openRegistry(user);
    const dialog = await openRegisterDialog(user);

    expect(within(dialog).getByRole('switch', { name: 'Tools' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(within(dialog).getByRole('switch', { name: 'Streaming' })).toHaveAttribute(
      'aria-checked',
      'true',
    );

    await user.type(within(dialog).getByLabelText('Model id'), 'cap-model');
    await user.type(within(dialog).getByLabelText('Upstream model'), 'cap-upstream');
    await user.type(within(dialog).getByLabelText('Context window'), '128000');
    await user.click(within(dialog).getByRole('switch', { name: 'Streaming' }));
    await user.click(within(dialog).getByRole('button', { name: 'Register model' }));

    expect(await screen.findByText("Model 'cap-model' registered.")).toBeInTheDocument();
    expect(posted).toEqual([
      {
        id: 'cap-model',
        provider: 'openai',
        upstream_model: 'cap-upstream',
        enabled: true,
        supports_tools: true,
        supports_streaming: false,
        context_window: 128000,
      },
    ]);
    expect(posted[0]).not.toHaveProperty('max_output_tokens');
  });

  it('rejects a capability number below 1 before sending', async () => {
    const posted: CreateModelInput[] = [];
    installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload([CHAT])),
      'POST /api/v1/models': (_url, init) => {
        posted.push(JSON.parse(String(init.body)) as CreateModelInput);
        return jsonResponse(CHAT, 201);
      },
    });
    const user = userEvent.setup();
    renderApp();

    await openRegistry(user);
    const dialog = await openRegisterDialog(user);

    await user.type(within(dialog).getByLabelText('Model id'), 'bad-cap');
    await user.type(within(dialog).getByLabelText('Upstream model'), 'bad-cap-upstream');
    await user.type(within(dialog).getByLabelText('Max output tokens'), '0');
    await user.click(within(dialog).getByRole('button', { name: 'Register model' }));

    expect(
      await within(dialog).findByText('Enter a whole number of 1 or more.'),
    ).toBeInTheDocument();
    expect(posted).toHaveLength(0);
  });

  it('blocks an invalid id and a blank upstream model before sending', async () => {
    const fetchMock = installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload([CHAT])),
    });
    const user = userEvent.setup();
    renderApp();

    await openRegistry(user);
    const dialog = await openRegisterDialog(user);

    await user.type(within(dialog).getByLabelText('Model id'), 'bad id');
    await user.click(within(dialog).getByRole('button', { name: 'Register model' }));

    expect(
      await within(dialog).findByText('Use only letters, numbers, and . _ : -'),
    ).toBeInTheDocument();
    expect(within(dialog).getByText('Enter the upstream model name.')).toBeInTheDocument();
    expect(modelCalls(fetchMock, 'POST')).toHaveLength(0);
    expect(screen.getByRole('dialog', { name: 'Register model' })).toBeInTheDocument();
  });

  it('keeps the dialog open and shows the code and request id on a duplicate model', async () => {
    installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload([CHAT])),
      'POST /api/v1/models': () =>
        jsonResponse(
          {
            error: {
              message: "Model 'chat-prod' already exists",
              type: 'invalid_request_error',
              param: 'id',
              code: 'duplicate_model',
              request_id: 'req_duplicate_model',
            },
          },
          409,
          { 'x-request-id': 'req_duplicate_model' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    await openRegistry(user);
    const dialog = await openRegisterDialog(user);
    const idInput = within(dialog).getByLabelText('Model id');

    await user.type(idInput, 'chat-prod');
    await user.type(within(dialog).getByLabelText('Upstream model'), 'gpt-4o-mini');
    await user.click(within(dialog).getByRole('button', { name: 'Register model' }));

    expect(await within(dialog).findByText('Could not register model')).toBeInTheDocument();
    expect(within(dialog).getByText('HTTP 409')).toBeInTheDocument();
    expect(within(dialog).getByText("Model 'chat-prod' already exists")).toBeInTheDocument();
    expect(within(dialog).getByText('duplicate_model')).toBeInTheDocument();
    expect(within(dialog).getByText('req_duplicate_model')).toBeInTheDocument();
    expect(idInput).toHaveValue('chat-prod');
    expect(within(dialog).getByRole('button', { name: 'Register model' })).toBeEnabled();
  });

  it('surfaces a provider that is not configured instead of guessing', async () => {
    installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload([CHAT])),
      'POST /api/v1/models': () =>
        jsonResponse(
          {
            error: {
              message: "Provider 'deepseek' is not configured on this backend",
              type: 'invalid_request_error',
              param: 'provider',
              code: 'provider_not_configured',
              request_id: 'req_provider_missing',
            },
          },
          400,
          { 'x-request-id': 'req_provider_missing' },
        ),
    });
    const user = userEvent.setup();
    renderApp();

    await openRegistry(user);
    const dialog = await openRegisterDialog(user);

    await user.type(within(dialog).getByLabelText('Model id'), 'deepseek-chat');
    await user.selectOptions(within(dialog).getByLabelText('Provider'), 'deepseek');
    await user.type(within(dialog).getByLabelText('Upstream model'), 'deepseek-chat');
    await user.click(within(dialog).getByRole('button', { name: 'Register model' }));

    expect(
      await within(dialog).findByText("Provider 'deepseek' is not configured on this backend"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText('provider_not_configured')).toBeInTheDocument();
    expect(within(dialog).getByText('req_provider_missing')).toBeInTheDocument();
  });

  it('deletes a model only after confirmation and removes the row', async () => {
    let models = [CHAT, LEGACY];
    const fetchMock = installFetchMock({
      '/api/v1/models': () => jsonResponse(modelPayload(models)),
      'DELETE /api/v1/models/:id': (url) => {
        const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
        models = models.filter((model) => model.id !== id);
        return new Response(null, { status: 204 });
      },
    });
    const user = userEvent.setup();
    renderApp();

    const table = await openRegistry(user);
    await user.click(within(table).getByRole('button', { name: 'Delete chat-prod' }));

    const dialog = await screen.findByRole('dialog', { name: 'Delete model' });
    expect(within(dialog).getByText('chat-prod')).toBeInTheDocument();
    expect(deleteModelCalls(fetchMock)).toHaveLength(0);

    await user.click(within(dialog).getByRole('button', { name: 'Delete model' }));

    expect(await screen.findByText("Model 'chat-prod' deleted.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    await waitFor(() => {
      const updatedTable = screen.getByRole('table', { name: 'Registered models' });
      expect(within(updatedTable).queryByText('chat-prod')).not.toBeInTheDocument();
      expect(within(updatedTable).getByText('legacy-chat')).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(document.activeElement).toBe(
        screen.getByRole('heading', { name: 'Models', level: 2 }),
      );
    });

    const deleteCalls = deleteModelCalls(fetchMock);
    expect(deleteCalls).toHaveLength(1);
    const call = deleteCalls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;
    expect(toUrl(call[0]).pathname).toBe('/api/v1/models/chat-prod');
  });
});
