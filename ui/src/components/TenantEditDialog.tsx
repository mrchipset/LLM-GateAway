import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import type { TenantLimitsPatch, TenantSummary } from '../api/client';
import { useUpdateTenantLimits } from '../hooks/useTenantMutations';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface TenantEditDialogProps {
  masterKey: string;
  tenant: TenantSummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onSaved: (message: string) => void;
}

type LimitFieldResult =
  | { status: 'unchanged' }
  | { status: 'set'; value: number | null }
  | { status: 'invalid'; message: string };

interface LimitFieldErrors {
  quota?: string;
  rate?: string;
}

function limitToInput(value: number | null): string {
  return value === null ? '' : String(value);
}

function parseLimitField(raw: string, original: string): LimitFieldResult {
  const value = raw.trim();
  if (value === original) return { status: 'unchanged' };
  if (value === '') return { status: 'set', value: null };
  if (!/^\d+$/.test(value)) {
    return { status: 'invalid', message: 'Enter a whole number of 1 or more.' };
  }

  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    return { status: 'invalid', message: 'Enter a whole number of 1 or more.' };
  }

  return { status: 'set', value: parsed };
}

export function TenantEditDialog({
  masterKey,
  tenant,
  returnFocusRef,
  onClose,
  onSaved,
}: TenantEditDialogProps) {
  const originalQuota = limitToInput(tenant.monthly_token_quota);
  const originalRate = limitToInput(tenant.requests_per_minute);
  const [quota, setQuota] = useState(originalQuota);
  const [rate, setRate] = useState(originalRate);
  const [auditEnabled, setAuditEnabled] = useState(tenant.audit_enabled);
  const [fieldErrors, setFieldErrors] = useState<LimitFieldErrors>({});
  const titleId = useId();
  const quotaId = useId();
  const rateId = useId();
  const auditLabelId = useId();
  const auditHintId = useId();
  const hintId = useId();
  const quotaErrorId = useId();
  const rateErrorId = useId();
  const quotaRef = useRef<HTMLInputElement>(null);
  const updateMutation = useUpdateTenantLimits(masterKey);

  const quotaDirty = quota.trim() !== originalQuota;
  const rateDirty = rate.trim() !== originalRate;
  const auditDirty = auditEnabled !== tenant.audit_enabled;
  const limitsDirty = quotaDirty || rateDirty;
  const hasChanges = limitsDirty || auditDirty;

  const clearing: string[] = [];
  if (quotaDirty && quota.trim() === '') clearing.push('monthly token quota');
  if (rateDirty && rate.trim() === '') clearing.push('requests per minute');

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const quotaResult = parseLimitField(quota, originalQuota);
    const rateResult = parseLimitField(rate, originalRate);
    const nextErrors: LimitFieldErrors = {};
    if (quotaResult.status === 'invalid') nextErrors.quota = quotaResult.message;
    if (rateResult.status === 'invalid') nextErrors.rate = rateResult.message;
    setFieldErrors(nextErrors);
    if (nextErrors.quota !== undefined || nextErrors.rate !== undefined) return;

    const patch: TenantLimitsPatch = {};
    if (quotaResult.status === 'set') patch.monthly_token_quota = quotaResult.value;
    if (rateResult.status === 'set') patch.requests_per_minute = rateResult.value;
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
                setFieldErrors((current) => ({ ...current, quota: undefined }));
                if (updateMutation.isError) updateMutation.reset();
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
                setFieldErrors((current) => ({ ...current, rate: undefined }));
                if (updateMutation.isError) updateMutation.reset();
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
        </div>

        {clearing.length > 0 && (
          <p className="mt-3 rounded border border-warn/30 bg-warn-soft px-2.5 py-1.5 text-[11.5px] text-warn">
            Will clear: {clearing.join(' and ')}.
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
