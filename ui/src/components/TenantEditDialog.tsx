import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import type { TenantLimitsPatch, TenantSummary } from '../api/client';
import { useUpdateTenantLimits } from '../hooks/useTenantMutations';
import { countErrorText, parseCountChange, type CountChangeResult } from '../lib/limits';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface TenantEditDialogProps {
  tenant: TenantSummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onSaved: (message: string) => void;
}

interface LimitFieldErrors {
  quota?: string;
  rate?: string;
  tokens?: string;
  concurrent?: string;
  retention?: string;
}

function limitToInput(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : String(value);
}

export function TenantEditDialog({
  tenant,
  returnFocusRef,
  onClose,
  onSaved,
}: TenantEditDialogProps) {
  const originalQuota = limitToInput(tenant.monthly_token_quota);
  const originalRate = limitToInput(tenant.requests_per_minute);
  const originalTokens = limitToInput(tenant.tokens_per_minute);
  const originalConcurrent = limitToInput(tenant.max_concurrent_requests);
  const originalRetention = limitToInput(tenant.audit_retention_days);
  const [quota, setQuota] = useState(originalQuota);
  const [rate, setRate] = useState(originalRate);
  const [tokens, setTokens] = useState(originalTokens);
  const [concurrent, setConcurrent] = useState(originalConcurrent);
  const [retention, setRetention] = useState(originalRetention);
  const [auditEnabled, setAuditEnabled] = useState(tenant.audit_enabled);
  const [fieldErrors, setFieldErrors] = useState<LimitFieldErrors>({});
  const titleId = useId();
  const quotaId = useId();
  const rateId = useId();
  const tokensId = useId();
  const concurrentId = useId();
  const retentionId = useId();
  const auditLabelId = useId();
  const auditHintId = useId();
  const hintId = useId();
  const retentionHintId = useId();
  const quotaErrorId = useId();
  const rateErrorId = useId();
  const tokensErrorId = useId();
  const concurrentErrorId = useId();
  const retentionErrorId = useId();
  const quotaRef = useRef<HTMLInputElement>(null);
  const updateMutation = useUpdateTenantLimits();

  const quotaDirty = quota.trim() !== originalQuota;
  const rateDirty = rate.trim() !== originalRate;
  const tokensDirty = tokens.trim() !== originalTokens;
  const concurrentDirty = concurrent.trim() !== originalConcurrent;
  const retentionDirty = retention.trim() !== originalRetention;
  const auditDirty = auditEnabled !== tenant.audit_enabled;
  const limitsDirty = quotaDirty || rateDirty || tokensDirty || concurrentDirty || retentionDirty;
  const hasChanges = limitsDirty || auditDirty;

  const clearing: string[] = [];
  if (quotaDirty && quota.trim() === '') clearing.push('monthly token quota');
  if (rateDirty && rate.trim() === '') clearing.push('requests per minute');
  if (tokensDirty && tokens.trim() === '') clearing.push('tokens per minute');
  if (concurrentDirty && concurrent.trim() === '') clearing.push('concurrency');

  const clearFieldError = (field: keyof LimitFieldErrors) => {
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
    if (updateMutation.isError) updateMutation.reset();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const quotaResult = parseCountChange(quota, originalQuota, 1);
    const rateResult = parseCountChange(rate, originalRate, 1);
    const tokensResult = parseCountChange(tokens, originalTokens, 1);
    const concurrentResult = parseCountChange(concurrent, originalConcurrent, 1);
    const retentionResult = parseCountChange(retention, originalRetention, 0);
    const nextErrors: LimitFieldErrors = {};
    if (quotaResult.status === 'invalid') nextErrors.quota = countErrorText(1);
    if (rateResult.status === 'invalid') nextErrors.rate = countErrorText(1);
    if (tokensResult.status === 'invalid') nextErrors.tokens = countErrorText(1);
    if (concurrentResult.status === 'invalid') nextErrors.concurrent = countErrorText(1);
    if (retentionResult.status === 'invalid') nextErrors.retention = countErrorText(0);
    setFieldErrors(nextErrors);
    if (Object.values(nextErrors).some((message) => message !== undefined)) return;

    const patch: TenantLimitsPatch = {};
    applyPatch(patch, 'monthly_token_quota', quotaResult);
    applyPatch(patch, 'requests_per_minute', rateResult);
    applyPatch(patch, 'tokens_per_minute', tokensResult);
    applyPatch(patch, 'max_concurrent_requests', concurrentResult);
    applyPatch(patch, 'audit_retention_days', retentionResult);
    if (auditDirty) patch.audit_enabled = auditEnabled;
    if (Object.keys(patch).length === 0) return;

    updateMutation.mutate(
      { tenantId: tenant.id, patch },
      {
        onSuccess: (updated) => {
          onSaved(
            limitsDirty
              ? `Limits updated for ${updated.name}.`
              : `Audit collection updated for ${updated.name}.`,
          );
        },
      },
    );
  };

  const quotaDescribedBy = fieldErrors.quota === undefined ? hintId : `${hintId} ${quotaErrorId}`;
  const rateDescribedBy = fieldErrors.rate === undefined ? hintId : `${hintId} ${rateErrorId}`;
  const tokensDescribedBy =
    fieldErrors.tokens === undefined ? hintId : `${hintId} ${tokensErrorId}`;
  const concurrentDescribedBy =
    fieldErrors.concurrent === undefined ? hintId : `${hintId} ${concurrentErrorId}`;
  const retentionDescribedBy =
    fieldErrors.retention === undefined
      ? retentionHintId
      : `${retentionHintId} ${retentionErrorId}`;

  return (
    <Modal
      labelledBy={titleId}
      onClose={onClose}
      closeDisabled={updateMutation.isPending}
      initialFocusRef={quotaRef}
      returnFocusRef={returnFocusRef}
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Access
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Edit tenant limits
          </h3>
          <p className="mt-1 break-all font-mono text-[11px] text-ink-muted">
            {tenant.name} · {tenant.id.slice(0, 8)}…
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={updateMutation.isPending}
          aria-label="Close edit limits dialog"
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
            <label htmlFor={quotaId} className="block text-[12px] font-medium text-ink">
              Monthly token quota
            </label>
            <input
              ref={quotaRef}
              id={quotaId}
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              value={quota}
              onChange={(event) => {
                setQuota(event.target.value);
                clearFieldError('quota');
              }}
              disabled={updateMutation.isPending}
              placeholder="No limit"
              aria-invalid={fieldErrors.quota !== undefined}
              aria-describedby={quotaDescribedBy}
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            />
            {fieldErrors.quota !== undefined && (
              <p id={quotaErrorId} role="alert" className="mt-1 text-xs text-danger">
                {fieldErrors.quota}
              </p>
            )}
          </div>

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

        <div className="mt-3">
          <label htmlFor={retentionId} className="block text-[12px] font-medium text-ink">
            Audit retention (days)
          </label>
          <input
            id={retentionId}
            type="number"
            min={0}
            step={1}
            inputMode="numeric"
            value={retention}
            onChange={(event) => {
              setRetention(event.target.value);
              clearFieldError('retention');
            }}
            disabled={updateMutation.isPending}
            placeholder="Inherit default"
            aria-invalid={fieldErrors.retention !== undefined}
            aria-describedby={retentionDescribedBy}
            className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted sm:max-w-xs"
          />
          <p id={retentionHintId} className="mt-1 text-[11px] leading-4 text-ink-muted">
            留空表示继承全局默认保留期；0 表示合规保留（永不自动删除）；正数表示保留天数。
          </p>
          {fieldErrors.retention !== undefined && (
            <p id={retentionErrorId} role="alert" className="mt-1 text-xs text-danger">
              {fieldErrors.retention}
            </p>
          )}
        </div>

        {clearing.length > 0 && (
          <p className="mt-3 rounded border border-warn/30 bg-warn-soft px-2.5 py-1.5 text-[11.5px] text-warn">
            Will clear: {clearing.join(' and ')}.
          </p>
        )}
        {retentionDirty && retention.trim() === '' && (
          <p className="mt-3 rounded border border-line bg-surface-sunken/60 px-2.5 py-1.5 text-[11.5px] text-ink-muted">
            Audit retention will use the global default.
          </p>
        )}

        <div className="mt-4 border-t border-line pt-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p id={auditLabelId} className="text-[12px] font-medium text-ink">
                Audit collection
              </p>
              <p id={auditHintId} className="mt-0.5 text-[11.5px] leading-4 text-ink-muted">
                Stores request/response content for this tenant. Off by default.
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={auditEnabled}
              aria-labelledby={auditLabelId}
              aria-describedby={auditHintId}
              disabled={updateMutation.isPending}
              onClick={() => {
                setAuditEnabled((current) => !current);
                if (updateMutation.isError) updateMutation.reset();
              }}
              className="inline-flex shrink-0 items-center gap-2 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span
                aria-hidden="true"
                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                  auditEnabled ? 'bg-accent' : 'bg-line-strong'
                }`}
              >
                <span
                  className={`absolute top-0.5 size-4 rounded-full bg-white shadow-sm transition-transform ${
                    auditEnabled ? 'translate-x-[1.125rem]' : 'translate-x-0.5'
                  }`}
                />
              </span>
              <span className="w-6 font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-muted">
                {auditEnabled ? 'On' : 'Off'}
              </span>
            </button>
          </div>
        </div>

        {updateMutation.isError && updateMutation.error !== null && (
          <div className="mt-3">
            <RequestErrorPanel
              error={updateMutation.error}
              title="Could not update tenant limits"
            />
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

type PatchKey =
  | 'monthly_token_quota'
  | 'requests_per_minute'
  | 'tokens_per_minute'
  | 'max_concurrent_requests'
  | 'audit_retention_days';

function applyPatch(patch: TenantLimitsPatch, key: PatchKey, result: CountChangeResult): void {
  if (result.status !== 'set') return;
  patch[key] = result.value;
}
