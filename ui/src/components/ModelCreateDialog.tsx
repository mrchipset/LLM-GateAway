import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import type { ModelProvider, ModelSummary } from '../api/client';
import { useCreateModel } from '../hooks/useModelMutations';
import {
  MODEL_PROVIDERS,
  MODEL_PROVIDER_LABELS,
  validateModelDraft,
  type ModelDraftErrors,
} from '../lib/models';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface ModelCreateDialogProps {
  masterKey: string;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onCreated: (model: ModelSummary) => void;
}

export function ModelCreateDialog({
  masterKey,
  returnFocusRef,
  onClose,
  onCreated,
}: ModelCreateDialogProps) {
  const [id, setId] = useState('');
  const [provider, setProvider] = useState<ModelProvider>('openai');
  const [upstreamModel, setUpstreamModel] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [fieldErrors, setFieldErrors] = useState<ModelDraftErrors>({});
  const titleId = useId();
  const idInput = useId();
  const providerId = useId();
  const upstreamId = useId();
  const enabledLabelId = useId();
  const enabledHintId = useId();
  const hintId = useId();
  const providerHintId = useId();
  const idErrorId = useId();
  const upstreamErrorId = useId();
  const idRef = useRef<HTMLInputElement>(null);
  const createMutation = useCreateModel(masterKey);

  const pending = createMutation.isPending;

  const clearServerError = () => {
    if (createMutation.isError) createMutation.reset();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const nextErrors = validateModelDraft({ id, upstreamModel });
    setFieldErrors(nextErrors);
    if (nextErrors.id !== undefined || nextErrors.upstreamModel !== undefined) return;

    createMutation.mutate(
      { id, provider, upstream_model: upstreamModel.trim(), enabled },
      {
        onSuccess: (model) => {
          onCreated(model);
        },
      },
    );
  };

  const idDescribedBy = fieldErrors.id === undefined ? hintId : `${hintId} ${idErrorId}`;
  const upstreamDescribedBy =
    fieldErrors.upstreamModel === undefined ? hintId : `${hintId} ${upstreamErrorId}`;

  return (
    <Modal
      labelledBy={titleId}
      onClose={onClose}
      closeDisabled={pending}
      initialFocusRef={idRef}
      returnFocusRef={returnFocusRef}
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Registry
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Register model
          </h3>
          <p className="mt-1 text-[11.5px] text-ink-muted">
            Clients call the gateway with this model id.
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={pending}
          aria-label="Close register model dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <form noValidate onSubmit={handleSubmit} className="px-5 py-4" aria-busy={pending}>
        <p id={hintId} className="text-[11.5px] leading-5 text-ink-muted">
          The id is what clients send in requests. The upstream model is the name the provider
          expects.
        </p>

        <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div>
            <label htmlFor={idInput} className="block text-[12px] font-medium text-ink">
              Model id
            </label>
            <input
              ref={idRef}
              id={idInput}
              type="text"
              value={id}
              onChange={(event) => {
                setId(event.target.value);
                setFieldErrors((current) => ({ ...current, id: undefined }));
                clearServerError();
              }}
              disabled={pending}
              autoComplete="off"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              aria-invalid={fieldErrors.id !== undefined}
              aria-describedby={idDescribedBy}
              placeholder="e.g. gpt-4o-mini"
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            />
            {fieldErrors.id !== undefined && (
              <p id={idErrorId} role="alert" className="mt-1 text-xs text-danger">
                {fieldErrors.id}
              </p>
            )}
          </div>

          <div>
            <label htmlFor={providerId} className="block text-[12px] font-medium text-ink">
              Provider
            </label>
            <select
              id={providerId}
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value as ModelProvider);
                clearServerError();
              }}
              disabled={pending}
              aria-describedby={providerHintId}
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            >
              {MODEL_PROVIDERS.map((option) => (
                <option key={option} value={option}>
                  {MODEL_PROVIDER_LABELS[option]}
                </option>
              ))}
            </select>
            <p id={providerHintId} className="mt-1 text-[11px] leading-4 text-ink-muted">
              This provider must already be configured on the backend. If it is not, the request is
              rejected and the reason is shown here.
            </p>
          </div>
        </div>

        <div className="mt-3">
          <label htmlFor={upstreamId} className="block text-[12px] font-medium text-ink">
            Upstream model
          </label>
          <input
            id={upstreamId}
            type="text"
            value={upstreamModel}
            onChange={(event) => {
              setUpstreamModel(event.target.value);
              setFieldErrors((current) => ({ ...current, upstreamModel: undefined }));
              clearServerError();
            }}
            disabled={pending}
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            aria-invalid={fieldErrors.upstreamModel !== undefined}
            aria-describedby={upstreamDescribedBy}
            placeholder="e.g. gpt-4o-mini-2024-07-18"
            className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
          />
          {fieldErrors.upstreamModel !== undefined && (
            <p id={upstreamErrorId} role="alert" className="mt-1 text-xs text-danger">
              {fieldErrors.upstreamModel}
            </p>
          )}
        </div>

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
              disabled={pending}
              onClick={() => {
                setEnabled((current) => !current);
                clearServerError();
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

        {createMutation.isError && createMutation.error !== null && (
          <div className="mt-3">
            <RequestErrorPanel error={createMutation.error} title="Could not register model" />
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2 border-t border-line pt-3">
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" disabled={pending}>
            {pending ? 'Registering…' : 'Register model'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
