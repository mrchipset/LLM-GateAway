import { useRef, useState } from 'react';

import type { ModelSummary } from '../api/client';
import type { ModelsQuery } from '../hooks/useModels';
import { formatCreatedAt, formatUpdatedAt } from '../lib/format';
import { Button } from './Button';
import { CheckCircleIcon, KeyIcon, RefreshIcon, TagIcon, TrashIcon } from './Icons';
import { ModelCreateDialog } from './ModelCreateDialog';
import { ModelDeleteDialog } from './ModelDeleteDialog';
import { ModelPricingDialog } from './ModelPricingDialog';
import { Panel, PanelHeader } from './Panel';
import { RequestErrorPanel } from './RequestErrorPanel';

interface ModelsPanelProps {
  masterKey: string | null;
  query: ModelsQuery;
}

type DeleteModelHandler = (model: ModelSummary, trigger: HTMLButtonElement) => void;
type PriceModelHandler = (model: ModelSummary, trigger: HTMLButtonElement) => void;

export function ModelsPanel({ masterKey, query }: ModelsPanelProps) {
  const [notice, setNotice] = useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [deletingModel, setDeletingModel] = useState<ModelSummary | null>(null);
  const [pricingModel, setPricingModel] = useState<ModelSummary | null>(null);
  const registerButtonRef = useRef<HTMLButtonElement>(null);
  const deleteTriggerRef = useRef<HTMLElement | null>(null);
  const priceTriggerRef = useRef<HTMLElement | null>(null);

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

  return (
    <Panel labelledBy="models-heading">
      <PanelHeader id="models-heading" eyebrow="Registry" title="Models">
        <div className="flex flex-wrap items-center justify-end gap-2">
          {count !== null && (
            <span className="rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-ink">
              {count}
            </span>
          )}
          {masterKey !== null && (
            <>
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
              <Button ref={registerButtonRef} onClick={openRegister}>
                Register model
              </Button>
            </>
          )}
        </div>
      </PanelHeader>
      <div className="px-5 py-4" aria-busy={masterKey !== null && query.isFetching}>
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
          masterKey={masterKey}
          query={query}
          onRegister={openRegister}
          onDelete={handleDelete}
          onPricing={handlePricing}
        />
      </div>

      {registerOpen && masterKey !== null && (
        <ModelCreateDialog
          masterKey={masterKey}
          returnFocusRef={registerButtonRef}
          onClose={() => setRegisterOpen(false)}
          onCreated={(model) => {
            setRegisterOpen(false);
            setNotice(`Model '${model.id}' registered.`);
          }}
        />
      )}

      {deletingModel !== null && masterKey !== null && (
        <ModelDeleteDialog
          masterKey={masterKey}
          model={deletingModel}
          returnFocusRef={deleteTriggerRef}
          onClose={() => setDeletingModel(null)}
          onDeleted={(model) => {
            setDeletingModel(null);
            setNotice(`Model '${model.id}' deleted.`);
          }}
          onStale={() => {
            void query.refetch();
          }}
        />
      )}

      {pricingModel !== null && masterKey !== null && (
        <ModelPricingDialog
          masterKey={masterKey}
          model={pricingModel}
          returnFocusRef={priceTriggerRef}
          onClose={() => setPricingModel(null)}
        />
      )}
    </Panel>
  );
}

interface ModelsContentProps {
  masterKey: string | null;
  query: ModelsQuery;
  onRegister: () => void;
  onDelete: DeleteModelHandler;
  onPricing: PriceModelHandler;
}

function ModelsContent({ masterKey, query, onRegister, onDelete, onPricing }: ModelsContentProps) {
  if (masterKey === null) return <ConnectPrompt />;
  if (query.status === 'pending') return <ModelsSkeleton />;
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
        <EmptyRegistry onRegister={onRegister} />
      ) : (
        <ModelsTable models={query.data.items} onDelete={onDelete} onPricing={onPricing} />
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
            className="grid grid-cols-[1.5fr_0.8fr_1.3fr_0.7fr_1fr_0.4fr] gap-4 rounded border border-line/70 px-3 py-3"
          >
            {[0, 1, 2, 3, 4, 5].map((cell) => (
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

function EmptyRegistry({ onRegister }: { onRegister: () => void }) {
  return (
    <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
      <h3 className="text-sm font-semibold text-ink">No models registered</h3>
      <p className="mx-auto mt-1 max-w-md text-[13px] text-ink-muted">
        Register a model to make it available through the gateway. Its provider must already be
        configured on the backend.
      </p>
      <Button onClick={onRegister} className="mt-3">
        Register your first model
      </Button>
    </div>
  );
}

function ModelsTable({
  models,
  onDelete,
  onPricing,
}: {
  models: ModelSummary[];
  onDelete: DeleteModelHandler;
  onPricing: PriceModelHandler;
}) {
  return (
    <>
      <div className="hidden md:block">
        <table className="w-full table-fixed border-collapse text-left text-[13px]">
          <caption className="sr-only">Registered models</caption>
          <colgroup>
            <col className="w-[20%]" />
            <col className="w-[8%]" />
            <col className="w-[23%]" />
            <col className="w-[11%]" />
            <col className="w-[16%]" />
            <col className="w-[22%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-line">
              {['Model', 'Provider', 'Upstream model', 'Status', 'Created (UTC)', 'Actions'].map(
                (label, index) => (
                  <th
                    key={label}
                    scope="col"
                    className={`py-2 pr-3 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted last:pr-0 ${
                      index === 5 ? 'text-right' : 'text-left'
                    }`}
                  >
                    {label}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {models.map((model) => (
              <ModelRow key={model.id} model={model} onDelete={onDelete} onPricing={onPricing} />
            ))}
          </tbody>
        </table>
      </div>
      <ul className="divide-y divide-line md:hidden">
        {models.map((model) => (
          <ModelCard key={model.id} model={model} onDelete={onDelete} onPricing={onPricing} />
        ))}
      </ul>
    </>
  );
}

function ModelRow({
  model,
  onDelete,
  onPricing,
}: {
  model: ModelSummary;
  onDelete: DeleteModelHandler;
  onPricing: PriceModelHandler;
}) {
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
      <td className="py-2.5 pr-3 align-top font-mono text-[11.5px] tabular-nums">
        <time dateTime={model.created_at}>{formatCreatedAt(model.created_at)}</time>
      </td>
      <td className="py-2.5 text-right align-top">
        <div className="flex justify-end gap-0.5">
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
    </tr>
  );
}

function ModelCard({
  model,
  onDelete,
  onPricing,
}: {
  model: ModelSummary;
  onDelete: DeleteModelHandler;
  onPricing: PriceModelHandler;
}) {
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
      <div className="mt-2 flex justify-end gap-2">
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
