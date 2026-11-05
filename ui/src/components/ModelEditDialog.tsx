import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import {
  ApiRequestError,
  type ModelProvider,
  type ModelSummary,
  type UpdateModelInput,
} from '../api/client';
import { useUpdateModel } from '../hooks/useModelMutations';
import { countErrorText, limitToInput, parseCountChange } from '../lib/limits';
import {
  MODEL_PROVIDERS,
  MODEL_PROVIDER_LABELS,
  isModelProvider,
  validateUpstreamModel,
} from '../lib/models';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface ModelEditDialogProps {
  model: ModelSummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onSaved: (message: string) => void;
}

interface EditFieldErrors {
  rate?: string;
  tokens?: string;
  upstream?: string;
}

export function ModelEditDialog({ model, returnFocusRef, onClose, onSaved }: ModelEditDialogProps) {
  const originalProvider: ModelProvider = isModelProvider(model.provider)
    ? model.provider
    : 'openai';
  const originalUpstream = model.upstream_model;
  const originalRate = limitToInput(model.requests_per_minute);
  const originalTokens = limitToInput(model.tokens_per_minute);
  const [enabled, setEnabled] = useState(model.enabled);
  const [provider, setProvider] = useState<ModelProvider>(originalProvider);
  const [upstream, setUpstream] = useState(originalUpstream);
  const [rate, setRate] = useState(originalRate);
  const [tokens, setTokens] = useState(originalTokens);
  const [fieldErrors, setFieldErrors] = useState<EditFieldErrors>({});
  const titleId = useId();
  const providerId = useId();
  const upstreamId = useId();
  const rateId = useId();
  const tokensId = useId();
  const enabledLabelId = useId();
  const enabledHintId = useId();
  const routingHintId = useId();
  const hintId = useId();
  const upstreamErrorId = useId();
  const rateErrorId = useId();
  const tokensErrorId = useId();
  const providerRef = useRef<HTMLSelectElement>(null);
  const updateMutation = useUpdateModel();

  const enabledDirty = enabled !== model.enabled;
  const providerDirty = provider !== originalProvider;
  const upstreamDirty = upstream.trim() !== originalUpstream.trim();
  const rateDirty = rate.trim() !== originalRate;
  const tokensDirty = tokens.trim() !== originalTokens;
  const hasChanges = enabledDirty || providerDirty || upstreamDirty || rateDirty || tokensDirty;

  const clearing: string[] = [];
  if (rateDirty && rate.trim() === '') clearing.push('requests per minute');
  if (tokensDirty && tokens.trim() === '') clearing.push('tokens per minute');

  const clearFieldError = (field: keyof EditFieldErrors) => {
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
    if (updateMutation.isError) updateMutation.reset();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const rateResult = parseCountChange(rate, originalRate, 1);
    const tokensResult = parseCountChange(tokens, originalTokens, 1);
    const upstreamError = validateUpstreamModel(upstream);
    const nextErrors: EditFieldErrors = {};
    if (rateResult.status === 'invalid') nextErrors.rate = countErrorText(1);
    if (tokensResult.status === 'invalid') nextErrors.tokens = countErrorText(1);
    if (upstreamError !== undefined) nextErrors.upstream = upstreamError;
    setFieldErrors(nextErrors);
    if (Object.values(nextErrors).some((message) => message !== undefined)) return;

    const patch: UpdateModelInput = {};
    if (enabledDirty) patch.enabled = enabled;
    if (providerDirty) patch.provider = provider;
    if (upstreamDirty) patch.upstream_model = upstream.trim();
    if (rateResult.status === 'set') patch.requests_per_minute = rateResult.value;
    if (tokensResult.status === 'set') patch.tokens_per_minute = tokensResult.value;
    if (Object.keys(patch).length === 0) return;

    updateMutation.mutate(
      { modelId: model.id, patch },
      {
        onSuccess: () => {
          onSaved(`Model '${model.id}' updated.`);
        },
      },
    );
  };

  const upstreamDescribedBy =
    fieldErrors.upstream === undefined ? routingHintId : `${routingHintId} ${upstreamErrorId}`;
  const rateDescribedBy = fieldErrors.rate === undefined ? hintId : `${hintId} ${rateErrorId}`;
  const tokensDescribedBy =
    fieldErrors.tokens === undefined ? hintId : `${hintId} ${tokensErrorId}`;
  const routingConflict =
    updateMutation.error instanceof ApiRequestError &&
    updateMutation.error.code === 'model_has_deployments';

  return (
    <Modal
      labelledBy={titleId}
      onClose={onClose}
      closeDisabled={updateMutation.isPending}
      initialFocusRef={providerRef}
      returnFocusRef={returnFocusRef}
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Registry
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Edit model
          </h3>
          <p className="mt-1 break-words font-mono text-[11px] text-ink-muted">{model.id}</p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={updateMutation.isPending}
          aria-label="Close edit model dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <form
        noValidate
        onSubmit={handleSubmit}
        className="px-5 py-4"
        aria-busy={updateMutation.isPending}
      >
        <h4 className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
          Routing
        </h4>
        <p id={routingHintId} className="mt-1 text-[11.5px] leading-5 text-ink-muted">
          {
            '修改 Provider 或上游模型前，需先删除该模型的全部部署：部署会覆盖这两项默认值，未删除时保存会返回 409，修改不会生效。'
          }
        </p>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor={providerId} className="block text-[12px] font-medium text-ink">
              Provider
            </label>
            <select
              ref={providerRef}
              id={providerId}
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value as ModelProvider);
                clearFieldError('upstream');
              }}
              disabled={updateMutation.isPending}
              aria-describedby={routingHintId}
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            >
              {MODEL_PROVIDERS.map((option) => (
                <option key={option} value={option}>
                  {MODEL_PROVIDER_LABELS[option]}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor={upstreamId} className="block text-[12px] font-medium text-ink">
              Upstream model
            </label>
            <input
              id={upstreamId}
              type="text"
              value={upstream}
              onChange={(event) => {
                setUpstream(event.target.value);
                clearFieldError('upstream');
              }}
              disabled={updateMutation.isPending}
              autoComplete="off"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              aria-invalid={fieldErrors.upstream !== undefined}
              aria-describedby={upstreamDescribedBy}
              placeholder="e.g. gpt-4o-mini-2024-07-18"
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            />
            {fieldErrors.upstream !== undefined && (
              <p id={upstreamErrorId} role="alert" className="mt-1 text-xs text-danger">
                {fieldErrors.upstream}
              </p>
            )}
          </div>
        </div>

        <div className="mt-4 border-t border-line pt-3">
          <h4 className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
            Limits (optional)
          </h4>
          <p id={hintId} className="mt-1 text-[11.5px] leading-5 text-ink-muted">
            Leave a limit blank to clear it. Values must be whole numbers of 1 or more.
          </p>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor={rateId} className="block text-[12px] font-medium text-ink">
                Requests per minute
              </label>
              <input
                id={rateId}
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                value={rate}
                onChange={(event) => {
                  setRate(event.target.value);
                  clearFieldError('rate');
                }}
                disabled={updateMutation.isPending}
                placeholder="No limit"
                aria-invalid={fieldErrors.rate !== undefined}
                aria-describedby={rateDescribedBy}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              />
              {fieldErrors.rate !== undefined && (
                <p id={rateErrorId} role="alert" className="mt-1 text-xs text-danger">
                  {fieldErrors.rate}
                </p>
              )}
            </div>

            <div>
              <label htmlFor={tokensId} className="block text-[12px] font-medium text-ink">
                Tokens per minute
              </label>
              <input
                id={tokensId}
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                value={tokens}
                onChange={(event) => {
                  setTokens(event.target.value);
                  clearFieldError('tokens');
                }}
                disabled={updateMutation.isPending}
                placeholder="No limit"
                aria-invalid={fieldErrors.tokens !== undefined}
                aria-describedby={tokensDescribedBy}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              />
              {fieldErrors.tokens !== undefined && (
                <p id={tokensErrorId} role="alert" className="mt-1 text-xs text-danger">
                  {fieldErrors.tokens}
                </p>
              )}
            </div>
          </div>
        </div>

        {clearing.length > 0 && (
          <p className="mt-3 rounded border border-warn/30 bg-warn-soft px-2.5 py-1.5 text-[11.5px] text-warn">
            Will clear: {clearing.join(' and ')}.
          </p>
        )}

        <div className="mt-4 border-t border-line pt-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p id={enabledLabelId} className="text-[12px] font-medium text-ink">
                Enabled
              </p>
              <p id={enabledHintId} className="mt-0.5 text-[11.5px] leading-4 text-ink-muted">
                Disabled models stay registered but cannot serve requests.
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              aria-labelledby={enabledLabelId}
              aria-describedby={enabledHintId}
              disabled={updateMutation.isPending}
              onClick={() => {
                setEnabled((current) => !current);
                if (updateMutation.isError) updateMutation.reset();
              }}
              className="inline-flex shrink-0 items-center gap-2 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span
                aria-hidden="true"
                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                  enabled ? 'bg-accent' : 'bg-line-strong'
                }`}
              >
                <span
                  className={`absolute top-0.5 size-4 rounded-full bg-white shadow-sm transition-transform ${
                    enabled ? 'translate-x-[1.125rem]' : 'translate-x-0.5'
                  }`}
                />
              </span>
              <span className="w-6 font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-muted">
                {enabled ? 'On' : 'Off'}
              </span>
            </button>
          </div>
        </div>

        {updateMutation.isError && updateMutation.error !== null && (
          <div className="mt-3">
            <RequestErrorPanel error={updateMutation.error} title="Could not update model" />
            {routingConflict && (
              <p className="mt-2 rounded border border-warn/30 bg-warn-soft px-2.5 py-1.5 text-[11.5px] leading-5 text-warn">
                {
                  '该模型仍有部署。请先在「Deployments」对话框中删除全部部署，再保存 Provider 或上游模型的修改。'
                }
              </p>
            )}
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2 border-t border-line pt-3">
          <Button variant="secondary" onClick={onClose} disabled={updateMutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" disabled={updateMutation.isPending || !hasChanges}>
            {updateMutation.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
