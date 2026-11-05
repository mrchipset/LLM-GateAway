import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import type { ApiKeyLimitsPatch, ApiKeySummary } from '../api/client';
import { useUpdateApiKeyLimits } from '../hooks/useKeyMutations';
import { countErrorText, limitToInput, parseCountChange } from '../lib/limits';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface KeyLimitsDialogProps {
  apiKey: ApiKeySummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onSaved: (message: string) => void;
}

interface LimitFieldErrors {
  rate?: string;
  tokens?: string;
  concurrent?: string;
}

export function KeyLimitsDialog({
  apiKey,
  returnFocusRef,
  onClose,
  onSaved,
}: KeyLimitsDialogProps) {
  const originalRate = limitToInput(apiKey.requests_per_minute);
  const originalTokens = limitToInput(apiKey.tokens_per_minute);
  const originalConcurrent = limitToInput(apiKey.max_concurrent_requests);
  const [rate, setRate] = useState(originalRate);
  const [tokens, setTokens] = useState(originalTokens);
  const [concurrent, setConcurrent] = useState(originalConcurrent);
  const [fieldErrors, setFieldErrors] = useState<LimitFieldErrors>({});
  const titleId = useId();
  const rateId = useId();
  const tokensId = useId();
  const concurrentId = useId();
  const hintId = useId();
  const rateErrorId = useId();
  const tokensErrorId = useId();
  const concurrentErrorId = useId();
  const rateRef = useRef<HTMLInputElement>(null);
  const updateMutation = useUpdateApiKeyLimits();

  const rateDirty = rate.trim() !== originalRate;
  const tokensDirty = tokens.trim() !== originalTokens;
  const concurrentDirty = concurrent.trim() !== originalConcurrent;
  const hasChanges = rateDirty || tokensDirty || concurrentDirty;

  const clearing: string[] = [];
  if (rateDirty && rate.trim() === '') clearing.push('requests per minute');
  if (tokensDirty && tokens.trim() === '') clearing.push('tokens per minute');
  if (concurrentDirty && concurrent.trim() === '') clearing.push('concurrency');

  const clearFieldError = (field: keyof LimitFieldErrors) => {
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
    if (updateMutation.isError) updateMutation.reset();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const rateResult = parseCountChange(rate, originalRate, 1);
    const tokensResult = parseCountChange(tokens, originalTokens, 1);
    const concurrentResult = parseCountChange(concurrent, originalConcurrent, 1);
    const nextErrors: LimitFieldErrors = {};
    if (rateResult.status === 'invalid') nextErrors.rate = countErrorText(1);
    if (tokensResult.status === 'invalid') nextErrors.tokens = countErrorText(1);
    if (concurrentResult.status === 'invalid') nextErrors.concurrent = countErrorText(1);
    setFieldErrors(nextErrors);
    if (Object.values(nextErrors).some((message) => message !== undefined)) return;

    const patch: ApiKeyLimitsPatch = {};
    if (rateResult.status === 'set') patch.requests_per_minute = rateResult.value;
    if (tokensResult.status === 'set') patch.tokens_per_minute = tokensResult.value;
    if (concurrentResult.status === 'set') patch.max_concurrent_requests = concurrentResult.value;
    if (Object.keys(patch).length === 0) return;

    updateMutation.mutate(
      { keyId: apiKey.id, patch },
      {
        onSuccess: () => {
          onSaved('Key limits updated.');
        },
      },
    );
  };

  const rateDescribedBy = fieldErrors.rate === undefined ? hintId : `${hintId} ${rateErrorId}`;
  const tokensDescribedBy =
    fieldErrors.tokens === undefined ? hintId : `${hintId} ${tokensErrorId}`;
  const concurrentDescribedBy =
    fieldErrors.concurrent === undefined ? hintId : `${hintId} ${concurrentErrorId}`;

  return (
    <Modal
      labelledBy={titleId}
      onClose={onClose}
      closeDisabled={updateMutation.isPending}
      initialFocusRef={rateRef}
      returnFocusRef={returnFocusRef}
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Access
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Edit key limits
          </h3>
          <p className="mt-1 break-words text-[11.5px] text-ink-muted">
            {apiKey.name} · <span className="font-mono">{apiKey.key_prefix}</span>
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={updateMutation.isPending}
          aria-label="Close edit key limits dialog"
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
        <p id={hintId} className="text-[11.5px] leading-5 text-ink-muted">
          Leave a limit blank to clear it. Values must be whole numbers of 1 or more.
        </p>

        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor={rateId} className="block text-[12px] font-medium text-ink">
              Requests per minute
            </label>
            <input
              ref={rateRef}
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

          <div>
            <label htmlFor={concurrentId} className="block text-[12px] font-medium text-ink">
              Max concurrent requests
            </label>
            <input
              id={concurrentId}
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              value={concurrent}
              onChange={(event) => {
                setConcurrent(event.target.value);
                clearFieldError('concurrent');
              }}
              disabled={updateMutation.isPending}
              placeholder="No limit"
              aria-invalid={fieldErrors.concurrent !== undefined}
              aria-describedby={concurrentDescribedBy}
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            />
            {fieldErrors.concurrent !== undefined && (
              <p id={concurrentErrorId} role="alert" className="mt-1 text-xs text-danger">
                {fieldErrors.concurrent}
              </p>
            )}
          </div>
        </div>

        {clearing.length > 0 && (
          <p className="mt-3 rounded border border-warn/30 bg-warn-soft px-2.5 py-1.5 text-[11.5px] text-warn">
            Will clear: {clearing.join(' and ')}.
          </p>
        )}

        {updateMutation.isError && updateMutation.error !== null && (
          <div className="mt-3">
            <RequestErrorPanel error={updateMutation.error} title="Could not update key limits" />
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
