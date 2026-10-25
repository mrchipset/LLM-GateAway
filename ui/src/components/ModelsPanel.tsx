import { useState } from 'react';

import { ApiRequestError, type ModelSummary } from '../api/client';
import type { ModelsQuery } from '../hooks/useModels';
import { formatCreatedAt, formatUpdatedAt } from '../lib/format';
import { Button } from './Button';
import { KeyIcon, RefreshIcon } from './Icons';
import { Panel, PanelHeader } from './Panel';

const CURL_COMMAND =
  'curl -X POST http://127.0.0.1:4000/api/v1/models -H "Authorization: Bearer $GATEWAY_MASTER_KEY" -H "Content-Type: application/json" -d \'{"id":"gpt-4o-mini","provider":"openai","upstream_model":"gpt-4o-mini"}\'';

interface ModelsPanelProps {
  masterKey: string | null;
  query: ModelsQuery;
}

export function ModelsPanel({ masterKey, query }: ModelsPanelProps) {
  const count =
    query.status === 'success'
      ? query.data.items.length < query.data.total
        ? `Showing ${query.data.items.length} of ${query.data.total}`
        : query.data.total === 1
          ? '1 model'
          : `${query.data.total} models`
      : null;

  return (
    <Panel labelledBy="models-heading">
      <PanelHeader id="models-heading" eyebrow="Registry" title="Models">
        <div className="flex items-center gap-2">
          {count !== null && (
            <span className="rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-ink">
              {count}
            </span>
          )}
          {masterKey !== null && (
            <Button
              variant="ghost"
              onClick={() => void query.refetch()}
              disabled={query.isFetching}
              aria-label="Refresh models"
            >
              <RefreshIcon
                className={`size-3.5 ${query.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`}
              />
              <span className="hidden sm:inline">Refresh</span>
            </Button>
          )}
        </div>
      </PanelHeader>
      <div className="px-5 py-4" aria-busy={masterKey !== null && query.isFetching}>
        <ModelsContent masterKey={masterKey} query={query} />
      </div>
    </Panel>
  );
}

interface ModelsContentProps {
  masterKey: string | null;
  query: ModelsQuery;
}

function ModelsContent({ masterKey, query }: ModelsContentProps) {
  if (masterKey === null) return <ConnectPrompt />;
  if (query.status === 'pending') return <ModelsSkeleton />;
  if (query.status === 'error') {
    return <ModelsErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  return (
    <>
      {query.dataUpdatedAt > 0 && (
        <div className="mb-2.5 flex justify-end">
          <time
            dateTime={new Date(query.dataUpdatedAt).toISOString()}
            className="font-mono text-[10.5px] tabular-nums text-ink-muted"
          >
            Updated {formatUpdatedAt(query.dataUpdatedAt)}
          </time>
        </div>
      )}
      {query.data.items.length === 0 ? (
        <EmptyRegistry />
      ) : (
        <ModelsTable models={query.data.items} />
      )}
    </>
  );
}

function ConnectPrompt() {
  return (
    <div className="flex min-h-40 flex-col items-start justify-center gap-1.5 py-4">
      <KeyIcon className="size-5 text-ink-muted" />
      <p className="mt-1 text-sm font-medium text-ink">
        Connect a master key to load the registry.
      </p>
      <p className="max-w-md text-[13px] text-ink-muted">
        The key is sent only to the management API from this browser tab.
      </p>
    </div>
  );
}

function ModelsSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading models…</span>
      <div aria-hidden="true" className="space-y-2">
        {[0, 1, 2, 3].map((row) => (
          <div
            key={row}
            className="grid grid-cols-[1.5fr_0.8fr_1.3fr_0.7fr_1fr] gap-4 rounded border border-line/70 px-3 py-3"
          >
            <span className="h-3.5 w-4/5 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
            <span className="h-3.5 w-3/5 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
            <span className="h-3.5 w-3/4 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
            <span className="h-3.5 w-4/5 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
            <span className="h-3.5 w-full animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyRegistry() {
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(CURL_COMMAND);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  };

  return (
    <div className="py-1">
      <h3 className="text-sm font-semibold text-ink">No models registered</h3>
      <p className="mt-1 max-w-prose text-[13px] text-ink-muted">
        Register a model with the admin API. Its provider must already be configured on the backend.
      </p>
      <div className="mt-4">
        <div className="flex items-center justify-between gap-3">
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
            Register a model
          </p>
          <Button variant="ghost" onClick={() => void handleCopy()}>
            {copyState === 'copied' ? 'Copied' : 'Copy command'}
          </Button>
        </div>
        <pre className="mt-1.5 rounded-md border border-line bg-surface-sunken px-3 py-2.5 font-mono text-[11.5px] leading-relaxed break-all whitespace-pre-wrap text-ink">
          <code>{CURL_COMMAND}</code>
        </pre>
        {copyState === 'failed' && (
          <p className="mt-1.5 text-xs text-danger">Could not copy. Select the command instead.</p>
        )}
      </div>
    </div>
  );
}

interface ModelsErrorStateProps {
  error: Error;
  onRetry: () => void;
}

function ModelsErrorState({ error, onRetry }: ModelsErrorStateProps) {
  const requestError = error instanceof ApiRequestError ? error : null;
  const statusLine =
    requestError === null
      ? 'Request failed'
      : requestError.status === 0
        ? 'Network error'
        : `HTTP ${requestError.status}`;
  const code = requestError?.code ?? null;
  const requestId = requestError?.requestId ?? null;

  return (
    <div role="alert" className="rounded-md border border-danger/30 bg-danger-soft/60 p-4">
      <h3 className="text-sm font-semibold text-danger">Could not load models</h3>
      <p className="mt-1 font-mono text-[11.5px] text-ink">{statusLine}</p>
      <p className="mt-2 text-[13px] text-ink">{requestError?.message ?? error.message}</p>
      {(code !== null || requestId !== null) && (
        <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 border-t border-danger/20 pt-3 font-mono text-[11px]">
          {code !== null && (
            <>
              <dt className="text-ink-muted">Code</dt>
              <dd className="break-all text-ink">{code}</dd>
            </>
          )}
          {requestId !== null && (
            <>
              <dt className="text-ink-muted">Request ID</dt>
              <dd className="select-all break-all text-ink">{requestId}</dd>
            </>
          )}
        </dl>
      )}
      <Button
        variant="secondary"
        className="mt-4"
        onClick={onRetry}
        aria-label="Retry loading models"
      >
        Retry
      </Button>
    </div>
  );
}

function ModelsTable({ models }: { models: ModelSummary[] }) {
  return (
    <>
      <div className="hidden md:block">
        <table className="w-full table-fixed border-collapse text-left text-[13px]">
          <caption className="sr-only">Registered models</caption>
          <colgroup>
            <col className="w-[24%]" />
            <col className="w-[10%]" />
            <col className="w-[28%]" />
            <col className="w-[14%]" />
            <col className="w-[24%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-line">
              {['Model', 'Provider', 'Upstream model', 'Status', 'Created (UTC)'].map((label) => (
                <th
                  key={label}
                  scope="col"
                  className="py-2 pr-3 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted last:pr-0"
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {models.map((model) => (
              <ModelRow key={model.id} model={model} />
            ))}
          </tbody>
        </table>
      </div>
      <ul className="divide-y divide-line md:hidden">
        {models.map((model) => (
          <ModelCard key={model.id} model={model} />
        ))}
      </ul>
    </>
  );
}

function ModelRow({ model }: { model: ModelSummary }) {
  return (
    <tr
      className={`transition-colors hover:bg-surface-sunken/40 ${
        model.enabled ? 'text-ink' : 'bg-surface-sunken/30 text-ink-muted'
      }`}
    >
      <th
        scope="row"
        className="break-words py-2.5 pr-3 align-top font-mono text-[12.5px] font-medium"
      >
        {model.id}
      </th>
      <td className="break-words py-2.5 pr-3 align-top">{model.provider}</td>
      <td className="break-words py-2.5 pr-3 align-top font-mono text-[12px]">
        {model.upstream_model}
      </td>
      <td className="py-2.5 pr-3 align-top">
        <ModelStatusBadge enabled={model.enabled} />
      </td>
      <td className="py-2.5 align-top font-mono text-[11.5px] tabular-nums">
        <time dateTime={model.created_at}>{formatCreatedAt(model.created_at)}</time>
      </td>
    </tr>
  );
}

function ModelCard({ model }: { model: ModelSummary }) {
  return (
    <li className={`py-3 ${model.enabled ? '' : 'bg-surface-sunken/30'}`}>
      <div className="flex items-start justify-between gap-3">
        <p
          className={`break-words font-mono text-[12.5px] font-medium ${
            model.enabled ? 'text-ink' : 'text-ink-muted'
          }`}
        >
          {model.id}
        </p>
        <ModelStatusBadge enabled={model.enabled} />
      </div>
      <dl
        className={`mt-2 grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs ${
          model.enabled ? 'text-ink' : 'text-ink-muted'
        }`}
      >
        <dt className="text-ink-muted">Provider</dt>
        <dd className="break-words">{model.provider}</dd>
        <dt className="text-ink-muted">Upstream</dt>
        <dd className="break-words font-mono text-[11.5px]">{model.upstream_model}</dd>
        <dt className="text-ink-muted">Created</dt>
        <dd className="font-mono text-[11px] tabular-nums">
          <time dateTime={model.created_at}>{formatCreatedAt(model.created_at)}</time>
        </dd>
      </dl>
    </li>
  );
}

function ModelStatusBadge({ enabled }: { enabled: boolean }) {
  if (!enabled) {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-line-strong bg-surface-sunken px-1.5 py-0.5 text-[10.5px] font-medium text-ink-muted">
        <span className="size-1.5 rounded-full border border-ink-muted" aria-hidden="true" />
        Disabled
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 rounded border border-ok/25 bg-ok-soft px-1.5 py-0.5 text-[10.5px] font-medium text-ok">
      <span className="size-1.5 rounded-full bg-ok" aria-hidden="true" />
      Enabled
    </span>
  );
}
