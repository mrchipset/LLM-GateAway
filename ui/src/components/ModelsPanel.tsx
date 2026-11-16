import { useEffect, useRef, useState } from 'react';

import type { ModelSummary, ThroughputStats } from '../api/client';
import type { ModelsQuery } from '../hooks/useModels';
import { useThroughput } from '../hooks/useThroughput';
import {
  formatCompactNumber,
  formatCreatedAt,
  formatExactNumber,
  formatUpdatedAt,
} from '../lib/format';
import { Button } from './Button';
import { CheckCircleIcon, DeployIcon, EditIcon, RefreshIcon, TagIcon, TrashIcon } from './Icons';
import { DeploymentDialog } from './DeploymentDialog';
import { ModelCreateDialog } from './ModelCreateDialog';
import { ModelDeleteDialog } from './ModelDeleteDialog';
import { ModelEditDialog } from './ModelEditDialog';
import { ModelPricingDialog } from './ModelPricingDialog';
import { Panel, PanelHeader } from './Panel';
import { RequestErrorPanel } from './RequestErrorPanel';
import { useAdminSession } from '../lib/adminSessionContext';

interface ModelsPanelProps {
  query: ModelsQuery;
}

type DeleteModelHandler = (model: ModelSummary, trigger: HTMLButtonElement) => void;
type PriceModelHandler = (model: ModelSummary, trigger: HTMLButtonElement) => void;
type DeploymentsHandler = (model: ModelSummary, trigger: HTMLButtonElement) => void;
type EditModelHandler = (model: ModelSummary, trigger: HTMLButtonElement) => void;

export function ModelsPanel({ query }: ModelsPanelProps) {
  const { canWrite } = useAdminSession();
  const throughputQuery = useThroughput();
  const [notice, setNotice] = useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [deletingModel, setDeletingModel] = useState<ModelSummary | null>(null);
  const [pricingModel, setPricingModel] = useState<ModelSummary | null>(null);
  const [deploymentsModel, setDeploymentsModel] = useState<ModelSummary | null>(null);
  const [editingModel, setEditingModel] = useState<ModelSummary | null>(null);
  const registerButtonRef = useRef<HTMLButtonElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focusHeadingRef = useRef(false);
  const deleteTriggerRef = useRef<HTMLElement | null>(null);
  const priceTriggerRef = useRef<HTMLElement | null>(null);
  const deploymentTriggerRef = useRef<HTMLElement | null>(null);
  const editTriggerRef = useRef<HTMLElement | null>(null);

  const count =
    query.status === 'success'
      ? query.data.items.length < query.data.total
        ? `Showing ${query.data.items.length} of ${query.data.total}`
        : query.data.total === 1
          ? '1 model'
          : `${query.data.total} models`
      : null;

  const openRegister = () => {
    setNotice(null);
    setRegisterOpen(true);
  };

  // Deleting a model removes the row that owns the trigger, so returning focus to it
  // would strand keyboard users on the document body.
  useEffect(() => {
    if (!focusHeadingRef.current) return;
    focusHeadingRef.current = false;
    headingRef.current?.focus();
  });

  const handleDelete = (model: ModelSummary, trigger: HTMLButtonElement) => {
    setNotice(null);
    deleteTriggerRef.current = trigger;
    setDeletingModel(model);
  };

  const handlePricing = (model: ModelSummary, trigger: HTMLButtonElement) => {
    setNotice(null);
    priceTriggerRef.current = trigger;
    setPricingModel(model);
  };

  const handleDeployments = (model: ModelSummary, trigger: HTMLButtonElement) => {
    setNotice(null);
    deploymentTriggerRef.current = trigger;
    setDeploymentsModel(model);
  };

  const handleEdit = (model: ModelSummary, trigger: HTMLButtonElement) => {
    setNotice(null);
    editTriggerRef.current = trigger;
    setEditingModel(model);
  };

  return (
    <Panel labelledBy="models-heading">
      <PanelHeader id="models-heading" eyebrow="Registry" title="Models" titleRef={headingRef}>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {count !== null && (
            <span className="rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-ink">
              {count}
            </span>
          )}
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
          {canWrite && (
            <Button ref={registerButtonRef} onClick={openRegister}>
              Register model
            </Button>
          )}
        </div>
      </PanelHeader>
      <div className="px-5 py-4" aria-busy={query.isFetching}>
        {notice !== null && (
          <p
            role="status"
            className="mb-3 flex items-center gap-1.5 rounded border border-ok/25 bg-ok-soft px-2.5 py-1.5 text-[12px] text-ok"
          >
            <CheckCircleIcon className="size-3.5" />
            {notice}
          </p>
        )}
        <ModelsContent
          query={query}
          throughput={throughputQuery.data?.items ?? []}
          canWrite={canWrite}
          onRegister={openRegister}
          onDelete={handleDelete}
          onPricing={handlePricing}
          onDeployments={handleDeployments}
          onEdit={handleEdit}
        />
      </div>

      {canWrite && registerOpen && (
        <ModelCreateDialog
          returnFocusRef={registerButtonRef}
          onClose={() => setRegisterOpen(false)}
          onCreated={(model) => {
            setRegisterOpen(false);
            setNotice(`Model '${model.id}' registered.`);
          }}
        />
      )}

      {canWrite && deletingModel !== null && (
        <ModelDeleteDialog
          model={deletingModel}
          returnFocusRef={deleteTriggerRef}
          onClose={() => setDeletingModel(null)}
          onDeleted={(model) => {
            setDeletingModel(null);
            setNotice(`Model '${model.id}' deleted.`);
            focusHeadingRef.current = true;
          }}
          onStale={() => {
            void query.refetch();
          }}
        />
      )}

      {canWrite && pricingModel !== null && (
        <ModelPricingDialog
          model={pricingModel}
          returnFocusRef={priceTriggerRef}
          onClose={() => setPricingModel(null)}
        />
      )}

      {canWrite && deploymentsModel !== null && (
        <DeploymentDialog
          model={deploymentsModel}
          returnFocusRef={deploymentTriggerRef}
          onClose={() => setDeploymentsModel(null)}
        />
      )}

      {canWrite && editingModel !== null && (
        <ModelEditDialog
          model={editingModel}
          returnFocusRef={editTriggerRef}
          onClose={() => setEditingModel(null)}
          onSaved={(message) => {
            setEditingModel(null);
            setNotice(message);
          }}
        />
      )}
    </Panel>
  );
}

interface ModelsContentProps {
  query: ModelsQuery;
  throughput: ThroughputStats[];
  canWrite: boolean;
  onRegister: () => void;
  onDelete: DeleteModelHandler;
  onPricing: PriceModelHandler;
  onDeployments: DeploymentsHandler;
  onEdit: EditModelHandler;
}

function ModelsContent({
  query,
  throughput,
  canWrite,
  onRegister,
  onDelete,
  onPricing,
  onDeployments,
  onEdit,
}: ModelsContentProps) {
  if (query.isPending) return <ModelsSkeleton />;
  if (query.status === 'error') {
    return (
      <RequestErrorPanel
        error={query.error}
        title="Could not load models"
        retryLabel="Retry loading models"
        onRetry={() => void query.refetch()}
      />
    );
  }

  // A throughput failure must never block the table; rows fall back to a dash.
  const throughputByModel = new Map<string, ThroughputStats>(
    throughput.map((item) => [item.model, item]),
  );

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
        <EmptyRegistry canWrite={canWrite} onRegister={onRegister} />
      ) : (
        <ModelsTable
          models={query.data.items}
          throughputByModel={throughputByModel}
          canWrite={canWrite}
          onDelete={onDelete}
          onPricing={onPricing}
          onDeployments={onDeployments}
          onEdit={onEdit}
        />
      )}
    </>
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
            className="grid grid-cols-[1.5fr_0.8fr_1.3fr_0.7fr_0.7fr_1fr_0.4fr] gap-4 rounded border border-line/70 px-3 py-3"
          >
            {[0, 1, 2, 3, 4, 5, 6].map((cell) => (
              <span
                key={cell}
                className="h-3.5 w-4/5 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none"
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyRegistry({ canWrite, onRegister }: { canWrite: boolean; onRegister: () => void }) {
  return (
    <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
      <h3 className="text-sm font-semibold text-ink">No models registered</h3>
      <p className="mx-auto mt-1 max-w-md text-[13px] text-ink-muted">
        {canWrite
          ? 'Register a model to make it available through the gateway. Its provider must already be configured on the backend.'
          : 'No model has been registered on this gateway yet.'}
      </p>
      {canWrite && (
        <Button onClick={onRegister} className="mt-3">
          Register your first model
        </Button>
      )}
    </div>
  );
}

const SPEED_HEADER_DESCRIPTION =
  'P50 tokens per second, measured by this gateway worker for streamed requests over the last 15 minutes.';
const NO_SPEED_DESCRIPTION = 'No streamed requests in the last 15 minutes';

interface SpeedView {
  decode: number | null;
  prefill: number | null;
  primary: string | null;
  secondary: string | null;
  description: string;
  label: string;
}

function throughputSpeedView(stats: ThroughputStats | null): SpeedView {
  const decode =
    stats !== null && stats.decode_tokens_per_second_p50 !== null
      ? Math.round(stats.decode_tokens_per_second_p50)
      : null;
  const prefill =
    stats !== null && stats.prefill_tokens_per_second_p50 !== null
      ? Math.round(stats.prefill_tokens_per_second_p50)
      : null;

  const primary = decode ?? prefill;
  if (primary === null) {
    return {
      decode,
      prefill,
      primary: null,
      secondary: null,
      description: NO_SPEED_DESCRIPTION,
      label: NO_SPEED_DESCRIPTION,
    };
  }

  const exactParts: string[] = [];
  if (decode !== null) exactParts.push(`decode ${formatExactNumber(decode)} tok/s`);
  if (prefill !== null) exactParts.push(`prefill ${formatExactNumber(prefill)} tok/s`);
  const description = `Effective upstream throughput: ${exactParts.join(', ')} (P50, last 15 minutes, streamed requests only, measured by this worker).`;

  // Decode speed is the headline number; prompt processing is the fallback.
  const secondary =
    decode !== null && prefill !== null ? `prefill ${formatExactNumber(prefill)}` : null;

  return {
    decode,
    prefill,
    primary: `${formatExactNumber(primary)} tok/s`,
    secondary,
    description,
    label: description,
  };
}

function SpeedCell({ stats }: { stats: ThroughputStats | null }) {
  const view = throughputSpeedView(stats);
  if (view.primary === null) {
    return (
      <td
        className="py-2.5 pr-3 align-top font-mono text-[11px] tabular-nums text-ink-muted"
        title={view.description}
        aria-label={view.label}
      >
        —
      </td>
    );
  }

  return (
    <td
      className="py-2.5 pr-3 align-top font-mono text-[11.5px] tabular-nums"
      title={view.description}
      aria-label={view.label}
    >
      <span className="block">{view.primary}</span>
      {view.secondary !== null && (
        <span className="mt-0.5 block text-[11px] text-ink-muted">{view.secondary}</span>
      )}
    </td>
  );
}

function modelSpeedSummary(stats: ThroughputStats | null): { summary: string; exact: string } {
  const view = throughputSpeedView(stats);
  if (view.primary === null) {
    return { summary: '—', exact: view.description };
  }
  const parts: string[] = [];
  if (view.decode !== null) parts.push(`${formatExactNumber(view.decode)} dec`);
  if (view.prefill !== null) parts.push(`${formatExactNumber(view.prefill)} pre`);
  return { summary: `${parts.join(' · ')} tok/s`, exact: view.description };
}

function ModelsTable({
  models,
  throughputByModel,
  canWrite,
  onDelete,
  onPricing,
  onDeployments,
  onEdit,
}: {
  models: ModelSummary[];
  throughputByModel: Map<string, ThroughputStats>;
  canWrite: boolean;
  onDelete: DeleteModelHandler;
  onPricing: PriceModelHandler;
  onDeployments: DeploymentsHandler;
  onEdit: EditModelHandler;
}) {
  const columns: { label: string; description?: string }[] = [
    { label: 'Model' },
    { label: 'Provider' },
    { label: 'Upstream model' },
    { label: 'Status' },
    { label: 'Speed', description: SPEED_HEADER_DESCRIPTION },
    { label: 'Created (UTC)' },
  ];
  if (canWrite) columns.push({ label: 'Actions' });

  return (
    <>
      <div className="hidden md:block">
        <table className="w-full table-fixed border-collapse text-left text-[13px]">
          <caption className="sr-only">Registered models</caption>
          <colgroup>
            <col className={canWrite ? 'w-[18%]' : 'w-[22%]'} />
            <col className={canWrite ? 'w-[7%]' : 'w-[8%]'} />
            <col className={canWrite ? 'w-[20%]' : 'w-[26%]'} />
            <col className={canWrite ? 'w-[10%]' : 'w-[11%]'} />
            <col className={canWrite ? 'w-[14%]' : 'w-[15%]'} />
            <col className={canWrite ? 'w-[14%]' : 'w-[18%]'} />
            {canWrite && <col className="w-[17%]" />}
          </colgroup>
          <thead>
            <tr className="border-b border-line">
              {columns.map((column, index) => (
                <th
                  key={column.label}
                  scope="col"
                  className={`py-2 pr-3 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted last:pr-0 ${
                    index === columns.length - 1 && canWrite ? 'text-right' : 'text-left'
                  }`}
                  title={column.description}
                  aria-label={
                    column.description === undefined
                      ? undefined
                      : `${column.label}: ${column.description}`
                  }
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {models.map((model) => (
              <ModelRow
                key={model.id}
                model={model}
                stats={throughputByModel.get(model.id) ?? null}
                canWrite={canWrite}
                onDelete={onDelete}
                onPricing={onPricing}
                onDeployments={onDeployments}
                onEdit={onEdit}
              />
            ))}
          </tbody>
        </table>
      </div>
      <ul aria-label="Model cards" className="divide-y divide-line md:hidden">
        {models.map((model) => (
          <ModelCard
            key={model.id}
            model={model}
            stats={throughputByModel.get(model.id) ?? null}
            canWrite={canWrite}
            onDelete={onDelete}
            onPricing={onPricing}
            onDeployments={onDeployments}
            onEdit={onEdit}
          />
        ))}
      </ul>
    </>
  );
}

function formatTokenCapacity(value: number): string {
  if (value >= 1_000_000) return `${formatCompactNumber(value / 1_000_000)}m`;
  if (value >= 1_000) return `${formatCompactNumber(value / 1_000)}k`;
  return formatExactNumber(value);
}

function modelCapabilitySummary(model: ModelSummary): { summary: string; exact: string } | null {
  const parts: string[] = [];
  const exact: string[] = [];
  if (model.context_window !== null && model.context_window !== undefined) {
    parts.push(`${formatTokenCapacity(model.context_window)} ctx`);
    exact.push(`${formatExactNumber(model.context_window)} token context window`);
  }
  if (model.max_output_tokens !== null && model.max_output_tokens !== undefined) {
    parts.push(`${formatTokenCapacity(model.max_output_tokens)} out`);
    exact.push(`${formatExactNumber(model.max_output_tokens)} max output tokens`);
  }
  if (typeof model.supports_tools === 'boolean') {
    parts.push(model.supports_tools ? 'tools' : 'no tools');
    exact.push(model.supports_tools ? 'tools supported' : 'tools not supported');
  }
  if (typeof model.supports_streaming === 'boolean') {
    parts.push(model.supports_streaming ? 'stream' : 'no stream');
    exact.push(model.supports_streaming ? 'streaming supported' : 'streaming not supported');
  }
  if (parts.length === 0) return null;
  return { summary: parts.join(' · '), exact: `Model capabilities: ${exact.join(', ')}` };
}

function modelLimitSummary(model: ModelSummary): { summary: string; exact: string } | null {
  const parts: string[] = [];
  const exact: string[] = [];
  if (model.requests_per_minute !== null && model.requests_per_minute !== undefined) {
    parts.push(`${formatCompactNumber(model.requests_per_minute)} req/min`);
    exact.push(`${formatExactNumber(model.requests_per_minute)} requests per minute`);
  }
  if (model.tokens_per_minute !== null && model.tokens_per_minute !== undefined) {
    parts.push(`${formatCompactNumber(model.tokens_per_minute)} tok/min`);
    exact.push(`${formatExactNumber(model.tokens_per_minute)} tokens per minute`);
  }
  if (parts.length === 0) return null;
  return { summary: parts.join(' · '), exact: `Model limits: ${exact.join(', ')}` };
}

function ModelRow({
  model,
  stats,
  canWrite,
  onDelete,
  onPricing,
  onDeployments,
  onEdit,
}: {
  model: ModelSummary;
  stats: ThroughputStats | null;
  canWrite: boolean;
  onDelete: DeleteModelHandler;
  onPricing: PriceModelHandler;
  onDeployments: DeploymentsHandler;
  onEdit: EditModelHandler;
}) {
  const limits = modelLimitSummary(model);
  const capabilities = modelCapabilitySummary(model);
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
        {limits !== null && (
          <span
            className="mt-0.5 block break-words font-mono text-[10px] tabular-nums text-ink-muted"
            title={limits.exact}
          >
            {limits.summary}
          </span>
        )}
        {capabilities !== null && (
          <span
            className="mt-0.5 block break-words font-mono text-[10px] tabular-nums text-ink-muted"
            title={capabilities.exact}
          >
            {capabilities.summary}
          </span>
        )}
      </td>
      <td className="py-2.5 pr-3 align-top">
        <ModelStatusBadge enabled={model.enabled} />
      </td>
      <SpeedCell stats={stats} />
      <td className="py-2.5 pr-3 align-top font-mono text-[11.5px] tabular-nums">
        <time dateTime={model.created_at}>{formatCreatedAt(model.created_at)}</time>
      </td>
      {canWrite && (
        <td className="py-2.5 text-right align-top">
          <div className="flex justify-end gap-0.5">
            <Button
              variant="ghost"
              onClick={(event) => onEdit(model, event.currentTarget)}
              aria-label={`Edit ${model.id}`}
              title="Edit model"
              className="shrink-0 px-2 py-1 text-[12px]"
            >
              <EditIcon className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              onClick={(event) => onDeployments(model, event.currentTarget)}
              aria-label={`Deployments for ${model.id}`}
              title="Deployments"
              className="shrink-0 px-2 py-1 text-[12px]"
            >
              <DeployIcon className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              onClick={(event) => onPricing(model, event.currentTarget)}
              aria-label={`Pricing for ${model.id}`}
              title="Pricing"
              className="shrink-0 px-2 py-1 text-[12px]"
            >
              <TagIcon className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              onClick={(event) => onDelete(model, event.currentTarget)}
              aria-label={`Delete ${model.id}`}
              title="Delete model"
              className="shrink-0 px-2 py-1 text-[12px] text-danger hover:bg-danger-soft hover:text-danger"
            >
              <TrashIcon className="size-3.5" />
            </Button>
          </div>
        </td>
      )}
    </tr>
  );
}

function ModelCard({
  model,
  stats,
  canWrite,
  onDelete,
  onPricing,
  onDeployments,
  onEdit,
}: {
  model: ModelSummary;
  stats: ThroughputStats | null;
  canWrite: boolean;
  onDelete: DeleteModelHandler;
  onPricing: PriceModelHandler;
  onDeployments: DeploymentsHandler;
  onEdit: EditModelHandler;
}) {
  const limits = modelLimitSummary(model);
  const capabilities = modelCapabilitySummary(model);
  const speed = modelSpeedSummary(stats);
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
        <dt className="text-ink-muted">Speed</dt>
        <dd
          className="break-words font-mono text-[11px] tabular-nums text-ink-muted"
          title={speed.exact}
          aria-label={speed.exact}
        >
          {speed.summary}
        </dd>
        {limits !== null && (
          <>
            <dt className="text-ink-muted">Limits</dt>
            <dd className="break-words font-mono text-[11px]" title={limits.exact}>
              {limits.summary}
            </dd>
          </>
        )}
        {capabilities !== null && (
          <>
            <dt className="text-ink-muted">Capabilities</dt>
            <dd className="break-words font-mono text-[11px]" title={capabilities.exact}>
              {capabilities.summary}
            </dd>
          </>
        )}
        <dt className="text-ink-muted">Created</dt>
        <dd className="font-mono text-[11px] tabular-nums">
          <time dateTime={model.created_at}>{formatCreatedAt(model.created_at)}</time>
        </dd>
      </dl>
      {canWrite && (
        <div className="mt-2 flex flex-wrap justify-end gap-2">
          <Button
            variant="ghost"
            onClick={(event) => onEdit(model, event.currentTarget)}
            aria-label={`Edit ${model.id}`}
            className="shrink-0 px-2 py-1 text-[12px]"
          >
            <EditIcon className="size-3.5" />
            <span>Edit</span>
          </Button>
          <Button
            variant="ghost"
            onClick={(event) => onDeployments(model, event.currentTarget)}
            aria-label={`Deployments for ${model.id}`}
            className="shrink-0 px-2 py-1 text-[12px]"
          >
            <DeployIcon className="size-3.5" />
            <span>Deployments</span>
          </Button>
          <Button
            variant="ghost"
            onClick={(event) => onPricing(model, event.currentTarget)}
            aria-label={`Pricing for ${model.id}`}
            className="shrink-0 px-2 py-1 text-[12px]"
          >
            <TagIcon className="size-3.5" />
            <span>Pricing</span>
          </Button>
          <Button
            variant="ghost"
            onClick={(event) => onDelete(model, event.currentTarget)}
            aria-label={`Delete ${model.id}`}
            className="shrink-0 px-2 py-1 text-[12px] text-danger hover:bg-danger-soft hover:text-danger"
          >
            <TrashIcon className="size-3.5" />
            <span>Delete</span>
          </Button>
        </div>
      )}
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
