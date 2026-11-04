import { useId, useState, type RefObject } from 'react';

import type {
  ModelAccessMode,
  ModelSummary,
  TenantModelAccess,
  TenantSummary,
} from '../api/client';
import { useReplaceTenantModelAccess, useTenantModelAccess } from '../hooks/useModelAccess';
import { useModels, type ModelsQuery } from '../hooks/useModels';
import { modelProviderLabel } from '../lib/models';
import { Button } from './Button';
import { AlertTriangleIcon, CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface TenantModelAccessDialogProps {
  masterKey: string;
  tenant: TenantSummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onSaved: (message: string) => void;
}

export function TenantModelAccessDialog({
  masterKey,
  tenant,
  returnFocusRef,
  onClose,
  onSaved,
}: TenantModelAccessDialogProps) {
  const titleId = useId();
  const accessQuery = useTenantModelAccess(masterKey, tenant.id);
  const modelsQuery = useModels(masterKey);
  const replaceMutation = useReplaceTenantModelAccess(masterKey);

  return (
    <Modal
      labelledBy={titleId}
      onClose={onClose}
      closeDisabled={replaceMutation.isPending}
      returnFocusRef={returnFocusRef}
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Access
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Model access
          </h3>
          <p className="mt-1 break-words text-[11.5px] text-ink-muted">
            {tenant.name} · <span className="font-mono">{tenant.id.slice(0, 8)}…</span>
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={replaceMutation.isPending}
          aria-label="Close model access dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <div className="px-5 py-4" aria-busy={accessQuery.isPending}>
        {accessQuery.isPending && <AccessSkeleton />}
        {accessQuery.isError && (
          <RequestErrorPanel
            error={accessQuery.error}
            title="Could not load model access"
            retryLabel="Retry loading model access"
            onRetry={() => void accessQuery.refetch()}
          />
        )}
        {accessQuery.status === 'success' && (
          <ModelAccessForm
            tenant={tenant}
            current={accessQuery.data}
            modelsQuery={modelsQuery}
            replaceMutation={replaceMutation}
            onCancel={onClose}
            onSaved={onSaved}
          />
        )}
      </div>
    </Modal>
  );
}

function AccessSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading model access…</span>
      <div aria-hidden="true" className="space-y-2">
        {[0, 1, 2].map((row) => (
          <span
            key={row}
            className="block h-4 w-3/4 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none"
          />
        ))}
      </div>
    </div>
  );
}

type ReplaceMutation = ReturnType<typeof useReplaceTenantModelAccess>;

interface ModelAccessFormProps {
  tenant: TenantSummary;
  current: TenantModelAccess;
  modelsQuery: ModelsQuery;
  replaceMutation: ReplaceMutation;
  onCancel: () => void;
  onSaved: (message: string) => void;
}

function ModelAccessForm({
  tenant,
  current,
  modelsQuery,
  replaceMutation,
  onCancel,
  onSaved,
}: ModelAccessFormProps) {
  const [mode, setMode] = useState<ModelAccessMode>(current.mode);
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set(current.model_ids));
  const [filter, setFilter] = useState('');
  const modeGroupName = useId();
  const policyHintId = useId();
  const allId = useId();
  const allHintId = useId();
  const allowlistId = useId();
  const allowlistHintId = useId();
  const pickerHintId = useId();
  const searchId = useId();
  const listLabelId = useId();

  const pending = replaceMutation.isPending;
  const models = modelsQuery.status === 'success' ? modelsQuery.data.items : ([] as ModelSummary[]);
  const total = modelsQuery.status === 'success' ? modelsQuery.data.total : 0;
  const truncated = modelsQuery.status === 'success' && total > models.length;
  const knownIds = new Set(models.map((model) => model.id));
  const missingIds = current.model_ids.filter((modelId) => !knownIds.has(modelId)).sort();

  const query = filter.trim().toLowerCase();
  const visibleModels =
    query === ''
      ? models
      : models.filter(
          (model) =>
            model.id.toLowerCase().includes(query) ||
            model.upstream_model.toLowerCase().includes(query),
        );

  const toggleModel = (modelId: string) => {
    setSelected((currentSelection) => {
      const next = new Set(currentSelection);
      if (next.has(modelId)) next.delete(modelId);
      else next.add(modelId);
      return next;
    });
    if (replaceMutation.isError) replaceMutation.reset();
  };

  const handleSave = () => {
    const modelIds = mode === 'all' ? [] : [...selected].sort();
    replaceMutation.mutate(
      { tenantId: tenant.id, input: { mode, model_ids: modelIds } },
      {
        onSuccess: () => {
          onSaved(`Model access updated for ${tenant.name}.`);
        },
      },
    );
  };

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        handleSave();
      }}
      aria-busy={pending}
    >
      <fieldset>
        <legend className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
          Policy
        </legend>
        <p id={policyHintId} className="mt-1 text-[11.5px] leading-5 text-ink-muted">
          Saving replaces the whole policy for this tenant.
        </p>

        <div className="mt-2.5 space-y-2">
          <div className="flex items-start gap-2 rounded-md border border-line bg-surface-sunken/40 px-2.5 py-2">
            <input
              id={allId}
              type="radio"
              name={modeGroupName}
              value="all"
              checked={mode === 'all'}
              aria-describedby={allHintId}
              disabled={pending}
              onChange={() => {
                setMode('all');
                if (replaceMutation.isError) replaceMutation.reset();
              }}
              className="mt-0.5 size-3.5 shrink-0 accent-accent"
            />
            <div className="min-w-0">
              <label htmlFor={allId} className="block text-[12.5px] font-medium text-ink">
                All models
              </label>
              <p id={allHintId} className="mt-0.5 text-[11px] leading-4 text-ink-muted">
                Every enabled model, including models registered later.
              </p>
            </div>
          </div>

          <div className="flex items-start gap-2 rounded-md border border-line bg-surface-sunken/40 px-2.5 py-2">
            <input
              id={allowlistId}
              type="radio"
              name={modeGroupName}
              value="allowlist"
              checked={mode === 'allowlist'}
              aria-describedby={allowlistHintId}
              disabled={pending}
              onChange={() => {
                setMode('allowlist');
                if (replaceMutation.isError) replaceMutation.reset();
              }}
              className="mt-0.5 size-3.5 shrink-0 accent-accent"
            />
            <div className="min-w-0">
              <label htmlFor={allowlistId} className="block text-[12.5px] font-medium text-ink">
                Allowlist
              </label>
              <p id={allowlistHintId} className="mt-0.5 text-[11px] leading-4 text-ink-muted">
                Only the models selected below are usable.
              </p>
            </div>
          </div>
        </div>
      </fieldset>

      {mode === 'allowlist' && (
        <div className="mt-3">
          <div className="rounded-md border border-line">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
              <p
                id={listLabelId}
                className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
              >
                Allowed models
              </p>
              <span className="font-mono text-[10.5px] tabular-nums text-ink-muted">
                {selected.size} selected
              </span>
            </div>

            <div className="px-3 py-2">
              <label htmlFor={searchId} className="sr-only">
                Search models
              </label>
              <input
                id={searchId}
                type="search"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                disabled={pending || modelsQuery.status !== 'success' || models.length === 0}
                placeholder="Filter by id or upstream model"
                className="block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              />
              <p id={pickerHintId} className="mt-1 text-[11px] leading-4 text-ink-muted">
                {truncated
                  ? `Showing the first ${models.length} of ${total} registered models.`
                  : 'Only enabled models are routed; disabled models can still be selected.'}
              </p>
            </div>

            <ModelPickerList
              modelsQuery={modelsQuery}
              visibleModels={visibleModels}
              missingIds={missingIds}
              selected={selected}
              filter={filter}
              labelledBy={listLabelId}
              describedBy={pickerHintId}
              disabled={pending}
              onToggle={toggleModel}
            />
          </div>

          {selected.size === 0 && (
            <p className="mt-2 flex items-start gap-2 rounded border border-warn/30 bg-warn-soft px-2.5 py-2 text-[11.5px] text-warn">
              <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
              <span>
                No models selected. Saving this policy blocks every model for this tenant.
              </span>
            </p>
          )}
        </div>
      )}

      {replaceMutation.isError && replaceMutation.error !== null && (
        <div className="mt-3">
          <RequestErrorPanel error={replaceMutation.error} title="Could not update model access" />
        </div>
      )}

      <div className="mt-4 flex justify-end gap-2 border-t border-line pt-3">
        <Button variant="secondary" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </form>
  );
}

interface ModelPickerListProps {
  modelsQuery: ModelsQuery;
  visibleModels: ModelSummary[];
  missingIds: string[];
  selected: ReadonlySet<string>;
  filter: string;
  labelledBy: string;
  describedBy: string;
  disabled: boolean;
  onToggle: (modelId: string) => void;
}

function ModelPickerList({
  modelsQuery,
  visibleModels,
  missingIds,
  selected,
  filter,
  labelledBy,
  describedBy,
  disabled,
  onToggle,
}: ModelPickerListProps) {
  if (modelsQuery.isPending) {
    return (
      <div className="border-t border-line px-3 py-2.5">
        <span className="sr-only">Loading models…</span>
        <div aria-hidden="true" className="space-y-1.5">
          {[0, 1, 2].map((row) => (
            <span
              key={row}
              className="block h-3.5 w-2/3 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none"
            />
          ))}
        </div>
      </div>
    );
  }

  if (modelsQuery.isError) {
    return (
      <div className="border-t border-line p-3">
        <RequestErrorPanel
          error={modelsQuery.error}
          title="Could not load models"
          retryLabel="Retry loading models"
          onRetry={() => void modelsQuery.refetch()}
        />
        <p className="mt-2 text-[11px] text-ink-muted">
          You can still switch the policy to All models and save.
        </p>
      </div>
    );
  }

  if (modelsQuery.data.items.length === 0) {
    return (
      <p className="border-t border-line px-3 py-3 text-[11.5px] text-ink-muted">
        No models are registered yet. Register one in the Models tab.
      </p>
    );
  }

  return (
    <ul
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      className="max-h-56 space-y-px overflow-y-auto border-t border-line px-1.5 py-1.5"
    >
      {missingIds.map((modelId) => (
        <li key={modelId}>
          <label className="flex cursor-pointer items-start gap-2 rounded px-1.5 py-1 hover:bg-surface-sunken/70">
            <input
              type="checkbox"
              checked={selected.has(modelId)}
              disabled={disabled}
              onChange={() => onToggle(modelId)}
              aria-label={`${modelId} (not in the loaded model list)`}
              className="mt-0.5 size-3.5 shrink-0 accent-accent"
            />
            <span className="min-w-0">
              <span className="block break-words font-mono text-[12px] text-ink">{modelId}</span>
              <span className="block text-[10.5px] text-warn">Not in the loaded model list</span>
            </span>
          </label>
        </li>
      ))}

      {visibleModels.map((model) => (
        <li key={model.id}>
          <label className="flex cursor-pointer items-start gap-2 rounded px-1.5 py-1 hover:bg-surface-sunken/70">
            <input
              type="checkbox"
              checked={selected.has(model.id)}
              disabled={disabled}
              onChange={() => onToggle(model.id)}
              aria-label={`${model.id} (${model.upstream_model})`}
              className="mt-0.5 size-3.5 shrink-0 accent-accent"
            />
            <span className="min-w-0">
              <span className="block break-words font-mono text-[12px] text-ink">{model.id}</span>
              <span className="block break-words font-mono text-[10.5px] text-ink-muted">
                {model.upstream_model} · {modelProviderLabel(model.provider)}
              </span>
            </span>
          </label>
        </li>
      ))}

      {visibleModels.length === 0 && missingIds.length === 0 && (
        <li className="px-1.5 py-2 text-[11.5px] text-ink-muted">No models match “{filter}”.</li>
      )}
    </ul>
  );
}
