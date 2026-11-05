import { useId, useState, type RefObject } from 'react';

import type {
  AuditDeleteResult,
  AuditExportFormat,
  AuditExportQuery,
  TenantSummary,
} from '../api/client';
import { useDeleteAudit, useExportAudit } from '../hooks/useAudit';
import { useAdminSession } from '../lib/adminSessionContext';
import { downloadBlob } from '../lib/download';
import { formatExactNumber } from '../lib/format';
import { Button } from './Button';
import { AlertTriangleIcon, CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface AuditExportDialogProps {
  tenants: TenantSummary[];
  initialTenantId: string | null;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
}

interface FieldErrors {
  tenant?: string;
  since?: string;
  until?: string;
  before?: string;
}

function toLocalInput(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

function daysAgo(days: number): Date {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date;
}

function parseLocalInput(value: string): Date | null {
  if (value.trim() === '') return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function AuditExportDialog({
  tenants,
  initialTenantId,
  returnFocusRef,
  onClose,
}: AuditExportDialogProps) {
  const { canDeleteAudit } = useAdminSession();
  const [tenantId, setTenantId] = useState(initialTenantId ?? '');
  const [since, setSince] = useState(() => toLocalInput(daysAgo(30)));
  const [until, setUntil] = useState(() => toLocalInput(new Date()));
  const [format, setFormat] = useState<AuditExportFormat>('jsonl');
  const [before, setBefore] = useState(() => toLocalInput(daysAgo(90)));
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ before: string; result: AuditDeleteResult } | null>(
    null,
  );
  const [deleteResult, setDeleteResult] = useState<AuditDeleteResult | null>(null);
  const titleId = useId();
  const tenantIdInput = useId();
  const sinceId = useId();
  const untilId = useId();
  const formatId = useId();
  const beforeId = useId();
  const exportHintId = useId();
  const deleteHintId = useId();
  const tenantErrorId = useId();
  const sinceErrorId = useId();
  const untilErrorId = useId();
  const beforeErrorId = useId();

  const exportMutation = useExportAudit();
  const deleteMutation = useDeleteAudit();

  const clearError = (field: keyof FieldErrors) => {
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
  };

  const handleTenantChange = (value: string) => {
    setTenantId(value);
    clearError('tenant');
    setPreview(null);
    setDeleteResult(null);
    setExportNotice(null);
    if (exportMutation.isError) exportMutation.reset();
    if (deleteMutation.isError) deleteMutation.reset();
  };

  const handleExport = () => {
    const nextErrors: FieldErrors = {};
    if (tenantId === '') nextErrors.tenant = 'Select a tenant.';
    const sinceDate = parseLocalInput(since);
    const untilDate = parseLocalInput(until);
    if (sinceDate === null) {
      nextErrors.since = 'Enter a valid start time.';
    }
    if (untilDate === null) {
      nextErrors.until = 'Enter a valid end time.';
    } else if (sinceDate !== null && sinceDate.getTime() >= untilDate.getTime()) {
      nextErrors.until = 'The end time must be after the start time.';
    }
    setFieldErrors(nextErrors);
    if (Object.values(nextErrors).some((message) => message !== undefined)) return;
    if (sinceDate === null || untilDate === null) return;

    const query: AuditExportQuery = {
      tenantId,
      since: sinceDate.toISOString(),
      until: untilDate.toISOString(),
      format,
    };
    exportMutation.mutate(query, {
      onSuccess: ({ blob, filename }) => {
        downloadBlob(blob, filename);
        setExportNotice(`Downloaded ${filename}.`);
      },
    });
  };

  const beforeDate = preview === null ? null : preview.before;
  const beforeMatchesPreview =
    beforeDate !== null && parseLocalInput(before)?.toISOString() === beforeDate;

  const handlePreviewDelete = () => {
    const nextErrors: FieldErrors = {};
    if (tenantId === '') nextErrors.tenant = 'Select a tenant.';
    const parsedBefore = parseLocalInput(before);
    if (parsedBefore === null) {
      nextErrors.before = 'Enter a valid cutoff time.';
    } else if (parsedBefore.getTime() > Date.now()) {
      nextErrors.before = 'Choose a cutoff in the past.';
    }
    setFieldErrors(nextErrors);
    if (Object.values(nextErrors).some((message) => message !== undefined)) return;
    if (parsedBefore === null) return;

    const beforeIso = parsedBefore.toISOString();
    deleteMutation.mutate(
      { tenantId, before: beforeIso, dryRun: true },
      {
        onSuccess: (result) => {
          setPreview({ before: beforeIso, result });
          setDeleteResult(null);
        },
      },
    );
  };

  const handleDelete = () => {
    if (preview === null || !beforeMatchesPreview) return;
    deleteMutation.mutate(
      { tenantId, before: preview.before, dryRun: false },
      {
        onSuccess: (result) => {
          setDeleteResult(result);
          setPreview(null);
        },
      },
    );
  };

  const tenantDescribedBy = fieldErrors.tenant === undefined ? undefined : tenantErrorId;
  const sinceDescribedBy =
    fieldErrors.since === undefined ? exportHintId : `${exportHintId} ${sinceErrorId}`;
  const untilDescribedBy =
    fieldErrors.until === undefined ? exportHintId : `${exportHintId} ${untilErrorId}`;
  const beforeDescribedBy =
    fieldErrors.before === undefined ? deleteHintId : `${deleteHintId} ${beforeErrorId}`;

  return (
    <Modal
      labelledBy={titleId}
      onClose={onClose}
      closeDisabled={exportMutation.isPending || deleteMutation.isPending}
      returnFocusRef={returnFocusRef}
      panelClassName="max-w-xl"
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            History
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Audit export &amp; retention
          </h3>
          <p className="mt-1 text-[11.5px] text-ink-muted">
            Files stream straight to disk. Nothing is written to browser storage.
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={exportMutation.isPending || deleteMutation.isPending}
          aria-label="Close audit export dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <div className="px-5 py-4">
        <div>
          <label htmlFor={tenantIdInput} className="block text-[12px] font-medium text-ink">
            Tenant
          </label>
          <select
            id={tenantIdInput}
            value={tenantId}
            onChange={(event) => handleTenantChange(event.target.value)}
            disabled={exportMutation.isPending || deleteMutation.isPending}
            aria-invalid={fieldErrors.tenant !== undefined}
            aria-describedby={tenantDescribedBy}
            className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
          >
            <option value="">Select a tenant</option>
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
          {fieldErrors.tenant !== undefined && (
            <p id={tenantErrorId} role="alert" className="mt-1 text-xs text-danger">
              {fieldErrors.tenant}
            </p>
          )}
        </div>

        <section aria-labelledby={`${titleId}-export`} className="mt-4 border-t border-line pt-3">
          <h4
            id={`${titleId}-export`}
            className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted"
          >
            Export
          </h4>
          <p id={exportHintId} className="mt-1 text-[11.5px] leading-5 text-ink-muted">
            Downloads every captured request in the window for this tenant. Large windows can take a
            while.
          </p>

          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor={sinceId} className="block text-[12px] font-medium text-ink">
                From
              </label>
              <input
                id={sinceId}
                type="datetime-local"
                value={since}
                onChange={(event) => {
                  setSince(event.target.value);
                  setExportNotice(null);
                  clearError('since');
                  if (exportMutation.isError) exportMutation.reset();
                }}
                disabled={exportMutation.isPending}
                aria-invalid={fieldErrors.since !== undefined}
                aria-describedby={sinceDescribedBy}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              />
              {fieldErrors.since !== undefined && (
                <p id={sinceErrorId} role="alert" className="mt-1 text-xs text-danger">
                  {fieldErrors.since}
                </p>
              )}
            </div>
            <div>
              <label htmlFor={untilId} className="block text-[12px] font-medium text-ink">
                To
              </label>
              <input
                id={untilId}
                type="datetime-local"
                value={until}
                onChange={(event) => {
                  setUntil(event.target.value);
                  setExportNotice(null);
                  clearError('until');
                  if (exportMutation.isError) exportMutation.reset();
                }}
                disabled={exportMutation.isPending}
                aria-invalid={fieldErrors.until !== undefined}
                aria-describedby={untilDescribedBy}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              />
              {fieldErrors.until !== undefined && (
                <p id={untilErrorId} role="alert" className="mt-1 text-xs text-danger">
                  {fieldErrors.until}
                </p>
              )}
            </div>
          </div>

          <div className="mt-3">
            <label htmlFor={formatId} className="block text-[12px] font-medium text-ink">
              Format
            </label>
            <select
              id={formatId}
              value={format}
              onChange={(event) => {
                setFormat(event.target.value as AuditExportFormat);
                setExportNotice(null);
                if (exportMutation.isError) exportMutation.reset();
              }}
              disabled={exportMutation.isPending}
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted sm:max-w-xs"
            >
              <option value="jsonl">JSON Lines (.jsonl)</option>
              <option value="csv">CSV (.csv)</option>
            </select>
          </div>

          {exportNotice !== null && (
            <p
              role="status"
              className="mt-3 rounded border border-ok/25 bg-ok-soft px-2.5 py-1.5 text-[11.5px] text-ok"
            >
              {exportNotice}
            </p>
          )}

          {exportMutation.isError && exportMutation.error !== null && (
            <div className="mt-3">
              <RequestErrorPanel error={exportMutation.error} title="Could not export audit data" />
            </div>
          )}

          <div className="mt-3 flex justify-end">
            <Button onClick={handleExport} disabled={exportMutation.isPending}>
              {exportMutation.isPending ? 'Exporting…' : 'Export audit data'}
            </Button>
          </div>
        </section>

        {canDeleteAudit && (
          <section aria-labelledby={`${titleId}-delete`} className="mt-4 border-t border-line pt-3">
            <h4
              id={`${titleId}-delete`}
              className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted"
            >
              Delete (owner only)
            </h4>
            <p
              id={deleteHintId}
              className="mt-1 flex items-start gap-2 rounded border border-danger/30 bg-danger-soft/60 px-2.5 py-2 text-[11.5px] leading-5 text-danger"
            >
              <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
              <span>
                Permanently removes captured requests older than the cutoff for this tenant. Run a
                preview first; deletion cannot be undone.
              </span>
            </p>

            <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-end">
              <div className="min-w-0 flex-1">
                <label htmlFor={beforeId} className="block text-[12px] font-medium text-ink">
                  Delete requests before
                </label>
                <input
                  id={beforeId}
                  type="datetime-local"
                  value={before}
                  onChange={(event) => {
                    setBefore(event.target.value);
                    clearError('before');
                    setPreview(null);
                    setDeleteResult(null);
                    if (deleteMutation.isError) deleteMutation.reset();
                  }}
                  disabled={deleteMutation.isPending}
                  aria-invalid={fieldErrors.before !== undefined}
                  aria-describedby={beforeDescribedBy}
                  className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
                />
                {fieldErrors.before !== undefined && (
                  <p id={beforeErrorId} role="alert" className="mt-1 text-xs text-danger">
                    {fieldErrors.before}
                  </p>
                )}
              </div>
              <Button
                variant="secondary"
                onClick={handlePreviewDelete}
                disabled={deleteMutation.isPending}
                className="shrink-0"
              >
                {deleteMutation.isPending && preview === null ? 'Checking…' : 'Preview deletion'}
              </Button>
            </div>

            {preview !== null && (
              <div className="mt-3 rounded border border-line bg-surface-sunken/40 px-2.5 py-2">
                <p className="text-[11.5px] text-ink">
                  Preview only. Nothing has been deleted yet.
                </p>
                <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px]">
                  <dt className="text-ink-muted">requests_deleted</dt>
                  <dd className="tabular-nums text-ink">
                    {formatExactNumber(preview.result.requests_deleted)}
                  </dd>
                  <dt className="text-ink-muted">requests_remaining</dt>
                  <dd className="tabular-nums text-ink">
                    {formatExactNumber(preview.result.requests_remaining)}
                  </dd>
                </dl>
                {preview.result.requests_deleted === 0 ? (
                  <p className="mt-2 text-[11.5px] text-ink-muted">
                    No requests match this cutoff.
                  </p>
                ) : (
                  <div className="mt-2 flex justify-end">
                    <Button
                      onClick={handleDelete}
                      disabled={!beforeMatchesPreview || deleteMutation.isPending}
                      className="bg-danger text-white hover:bg-danger/90 disabled:bg-line-strong disabled:text-ink-muted"
                    >
                      {deleteMutation.isPending ? 'Deleting…' : 'Delete audit data permanently'}
                    </Button>
                  </div>
                )}
              </div>
            )}

            {deleteResult !== null && (
              <div
                role="status"
                className="mt-3 rounded border border-ok/25 bg-ok-soft px-2.5 py-2"
              >
                <p className="text-[11.5px] text-ok">Deletion complete.</p>
                <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px] text-ink">
                  <dt className="text-ink-muted">requests_deleted</dt>
                  <dd className="tabular-nums">
                    {formatExactNumber(deleteResult.requests_deleted)}
                  </dd>
                  <dt className="text-ink-muted">sessions_deleted</dt>
                  <dd className="tabular-nums">
                    {formatExactNumber(deleteResult.sessions_deleted)}
                  </dd>
                  <dt className="text-ink-muted">requests_remaining</dt>
                  <dd className="tabular-nums">
                    {formatExactNumber(deleteResult.requests_remaining)}
                  </dd>
                </dl>
                {deleteResult.requests_remaining > 0 && (
                  <p className="mt-1.5 text-[11.5px] text-ink-muted">
                    Requests older than the cutoff remain because the server limits each run. Run
                    the preview and delete again to continue.
                  </p>
                )}
              </div>
            )}

            {deleteMutation.isError && deleteMutation.error !== null && (
              <div className="mt-3">
                <RequestErrorPanel
                  error={deleteMutation.error}
                  title="Could not delete audit data"
                />
              </div>
            )}
          </section>
        )}
      </div>
    </Modal>
  );
}
