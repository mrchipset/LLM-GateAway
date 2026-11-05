import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import type { TenantLimitsPatch, TenantSummary } from '../api/client';
import { useDeleteTenant, useUpdateTenantLimits } from '../hooks/useTenantMutations';
import {
  countErrorText,
  limitToInput,
  parseCountChange,
  type CountChangeResult,
} from '../lib/limits';
import { validateTenantName } from '../lib/tenants';
import { Button } from './Button';
import { AlertTriangleIcon, CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface TenantEditDialogProps {
  tenant: TenantSummary;
  canDelete: boolean;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onSaved: (message: string) => void;
  onDeleted: (tenantId: string) => void;
}

interface LimitFieldErrors {
  quota?: string;
  rate?: string;
  tokens?: string;
  concurrent?: string;
  retention?: string;
}

const DANGER_BUTTON_CLASS =
  'bg-danger text-white hover:bg-danger/90 disabled:bg-line-strong disabled:text-ink-muted';

export function TenantEditDialog({
  tenant,
  canDelete,
  returnFocusRef,
  onClose,
  onSaved,
  onDeleted,
}: TenantEditDialogProps) {
  const originalName = tenant.name;
  const originalQuota = limitToInput(tenant.monthly_token_quota);
  const originalRate = limitToInput(tenant.requests_per_minute);
  const originalTokens = limitToInput(tenant.tokens_per_minute);
  const originalConcurrent = limitToInput(tenant.max_concurrent_requests);
  const originalRetention = limitToInput(tenant.audit_retention_days);
  const [name, setName] = useState(originalName);
  const [quota, setQuota] = useState(originalQuota);
  const [rate, setRate] = useState(originalRate);
  const [tokens, setTokens] = useState(originalTokens);
  const [concurrent, setConcurrent] = useState(originalConcurrent);
  const [retention, setRetention] = useState(originalRetention);
  const [auditEnabled, setAuditEnabled] = useState(tenant.audit_enabled);
  const [nameError, setNameError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<LimitFieldErrors>({});
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const titleId = useId();
  const nameId = useId();
  const nameHintId = useId();
  const nameErrorId = useId();
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
  const nameRef = useRef<HTMLInputElement>(null);
  const updateMutation = useUpdateTenantLimits();
  const deleteMutation = useDeleteTenant();
  const pending = updateMutation.isPending || deleteMutation.isPending;

  const trimmedName = name.trim();
  const nameDirty = trimmedName !== originalName;
  const quotaDirty = quota.trim() !== originalQuota;
  const rateDirty = rate.trim() !== originalRate;
  const tokensDirty = tokens.trim() !== originalTokens;
  const concurrentDirty = concurrent.trim() !== originalConcurrent;
  const retentionDirty = retention.trim() !== originalRetention;
  const auditDirty = auditEnabled !== tenant.audit_enabled;
  const limitsDirty = quotaDirty || rateDirty || tokensDirty || concurrentDirty || retentionDirty;
  const hasChanges = nameDirty || limitsDirty || auditDirty;

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
    if (confirmingDelete) return;

    const quotaResult = parseCountChange(quota, originalQuota, 1);
    const rateResult = parseCountChange(rate, originalRate, 1);
    const tokensResult = parseCountChange(tokens, originalTokens, 1);
    const concurrentResult = parseCountChange(concurrent, originalConcurrent, 1);
    const retentionResult = parseCountChange(retention, originalRetention, 0);
    const nextNameError = nameDirty ? validateTenantName(name) : undefined;
    const nextErrors: LimitFieldErrors = {};
    if (quotaResult.status === 'invalid') nextErrors.quota = countErrorText(1);
    if (rateResult.status === 'invalid') nextErrors.rate = countErrorText(1);
    if (tokensResult.status === 'invalid') nextErrors.tokens = countErrorText(1);
    if (concurrentResult.status === 'invalid') nextErrors.concurrent = countErrorText(1);
    if (retentionResult.status === 'invalid') nextErrors.retention = countErrorText(0);
    setNameError(nextNameError ?? null);
    setFieldErrors(nextErrors);
    if (
      nextNameError !== undefined ||
      Object.values(nextErrors).some((message) => message !== undefined)
    ) {
      return;
    }

    const patch: TenantLimitsPatch = {};
    if (nameDirty) patch.name = trimmedName;
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
          if (nameDirty) {
            onSaved(`Tenant renamed to ${updated.name}.`);
            return;
          }
          onSaved(
            limitsDirty
              ? `Limits updated for ${updated.name}.`
              : `Audit collection updated for ${updated.name}.`,
          );
        },
      },
    );
  };

  const handleDelete = () => {
    deleteMutation.mutate(tenant.id, {
      onSuccess: () => {
        onDeleted(tenant.id);
      },
    });
  };

  const nameDescribedBy = nameError === null ? nameHintId : `${nameHintId} ${nameErrorId}`;
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
      closeDisabled={pending}
      initialFocusRef={nameRef}
      returnFocusRef={returnFocusRef}
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Access
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Edit tenant
          </h3>
          <p className="mt-1 break-all font-mono text-[11px] text-ink-muted">
            {tenant.name} · {tenant.id.slice(0, 8)}…
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={pending}
          aria-label="Close edit tenant dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <form noValidate onSubmit={handleSubmit} className="px-5 py-4" aria-busy={pending}>
        <div>
          <label htmlFor={nameId} className="block text-[12px] font-medium text-ink">
            Tenant name
          </label>
          <input
            ref={nameRef}
            id={nameId}
            type="text"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setNameError(null);
              if (updateMutation.isError) updateMutation.reset();
            }}
            disabled={pending}
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            aria-invalid={nameError !== null}
            aria-describedby={nameDescribedBy}
            placeholder="e.g. Acme"
            className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
          />
          <p id={nameHintId} className="mt-1 text-[11px] leading-4 text-ink-muted">
            1–100 characters. Leading and trailing spaces are ignored.
          </p>
          {nameError !== null && (
            <p id={nameErrorId} role="alert" className="mt-1 text-xs text-danger">
              {nameError}
            </p>
          )}
        </div>

        <p id={hintId} className="mt-3 text-[11.5px] leading-5 text-ink-muted">
          Leave a limit blank to clear it. Values must be whole numbers of 1 or more.
        </p>

        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor={quotaId} className="block text-[12px] font-medium text-ink">
              Monthly token quota
            </label>
            <input
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
              disabled={pending}
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
              disabled={pending}
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
              disabled={pending}
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
              disabled={pending}
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
            disabled={pending}
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
              disabled={pending}
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

        {canDelete && (
          <div className="mt-4 rounded-md border border-danger/30 bg-danger-soft/40 px-3 py-2.5">
            <p className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-danger">
              Danger zone
            </p>
            {confirmingDelete ? (
              <>
                <p className="mt-1.5 text-[11.5px] leading-5 text-ink">
                  {
                    '删除后，该租户会从控制台列表中隐藏，其全部 API Key 立即失效；用量与审计历史仍会保留。此操作无法在控制台中撤销。'
                  }
                </p>
                <div className="mt-2 flex flex-wrap justify-end gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => setConfirmingDelete(false)}
                    disabled={pending}
                  >
                    Keep tenant
                  </Button>
                  <Button onClick={handleDelete} disabled={pending} className={DANGER_BUTTON_CLASS}>
                    {deleteMutation.isPending ? 'Deleting…' : 'Confirm delete'}
                  </Button>
                </div>
              </>
            ) : (
              <div className="mt-1 flex flex-wrap items-start justify-between gap-2">
                <p className="min-w-0 flex-1 text-[11.5px] leading-5 text-ink-muted">
                  <AlertTriangleIcon className="mr-1 inline size-3.5 align-[-2px] text-danger" />
                  Hides the tenant and revokes every API key. Usage and audit history is preserved.
                </p>
                <Button
                  variant="secondary"
                  onClick={() => {
                    setConfirmingDelete(true);
                    if (deleteMutation.isError) deleteMutation.reset();
                  }}
                  disabled={pending}
                  className="border border-danger/40 bg-surface text-danger hover:bg-danger-soft"
                >
                  Delete tenant
                </Button>
              </div>
            )}
            {deleteMutation.isError && deleteMutation.error !== null && (
              <div className="mt-2.5">
                <RequestErrorPanel error={deleteMutation.error} title="Could not delete tenant" />
              </div>
            )}
          </div>
        )}

        {updateMutation.isError && updateMutation.error !== null && (
          <div className="mt-3">
            <RequestErrorPanel error={updateMutation.error} title="Could not update tenant" />
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2 border-t border-line pt-3">
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" disabled={pending || !hasChanges || confirmingDelete}>
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
