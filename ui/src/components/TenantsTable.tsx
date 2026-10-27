import type { TenantSummary } from '../api/client';
import { formatCreatedAt, formatExactNumber } from '../lib/format';
import { Button } from './Button';
import { EditIcon } from './Icons';
import { TenantLimitFacts } from './TenantLimitFacts';

interface TenantsTableProps {
  tenants: TenantSummary[];
  onEdit: (tenant: TenantSummary, trigger: HTMLButtonElement) => void;
}

function shortId(tenant: TenantSummary): string {
  return `${tenant.id.slice(0, 8)}…`;
}

function AuditStatusBadge({ enabled }: { enabled: boolean }) {
  return (
    <span
      title={enabled ? 'Audit collection is on' : 'Audit collection is off'}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[10.5px] font-medium ${
        enabled
          ? 'border-ok/25 bg-ok-soft text-ok'
          : 'border-line-strong bg-surface-sunken text-ink-muted'
      }`}
    >
      <span
        aria-hidden="true"
        className={`size-1.5 rounded-full ${enabled ? 'bg-ok' : 'border border-ink-muted'}`}
      />
      {enabled ? 'On' : 'Off'}
    </span>
  );
}

function EditLimitButton({
  tenant,
  onEdit,
  withLabel = false,
}: {
  tenant: TenantSummary;
  onEdit: TenantsTableProps['onEdit'];
  withLabel?: boolean;
}) {
  return (
    <Button
      variant="ghost"
      onClick={(event) => onEdit(tenant, event.currentTarget)}
      aria-label={`Edit limits for ${tenant.name}`}
      className="shrink-0 px-2 py-1 text-[12px]"
    >
      <EditIcon className="size-3.5" />
      {withLabel && <span>Edit limits</span>}
    </Button>
  );
}

export function TenantsTable({ tenants, onEdit }: TenantsTableProps) {
  return (
    <>
      <div className="hidden md:block">
        <table className="w-full table-fixed border-collapse text-left text-[13px]">
          <caption className="sr-only">Tenants</caption>
          <colgroup>
            <col className="w-[23%]" />
            <col className="w-[13%]" />
            <col className="w-[19%]" />
            <col className="w-[20%]" />
            <col className="w-[13%]" />
            <col className="w-[12%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-line">
              {['Name', 'ID', 'Created (UTC)', 'Limits', 'Audit', 'Actions'].map((label, index) => (
                <th
                  key={label}
                  scope="col"
                  className={`py-2 pr-3 font-mono text-[10px] font-medium uppercase tracking-[0.1em] text-ink-muted last:pr-0 ${
                    index === 5 ? 'text-right' : 'text-left'
                  }`}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {tenants.map((tenant) => (
              <tr key={tenant.id} className="transition-colors hover:bg-surface-sunken/40">
                <th scope="row" className="break-words py-2.5 pr-3 align-top font-medium text-ink">
                  {tenant.name}
                </th>
                <td className="py-2.5 pr-3 align-top font-mono text-[11.5px]">
                  <span className="select-all break-all" title={tenant.id}>
                    {shortId(tenant)}
                  </span>
                </td>
                <td className="py-2.5 pr-3 align-top font-mono text-[11.5px] tabular-nums">
                  <time dateTime={tenant.created_at}>{formatCreatedAt(tenant.created_at)}</time>
                </td>
                <td className="py-2.5 pr-3 align-top">
                  <TenantLimitFacts tenant={tenant} variant="compact" />
                </td>
                <td className="py-2.5 pr-3 align-top">
                  <AuditStatusBadge enabled={tenant.audit_enabled} />
                </td>
                <td className="py-2.5 text-right align-top">
                  <EditLimitButton tenant={tenant} onEdit={onEdit} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul aria-label="Tenant cards" className="divide-y divide-line md:hidden">
        {tenants.map((tenant) => (
          <li key={tenant.id} className="py-3">
            <div className="flex items-start justify-between gap-3">
              <p className="break-words font-medium text-ink">{tenant.name}</p>
              <EditLimitButton tenant={tenant} onEdit={onEdit} withLabel />
            </div>
            <dl className="mt-2 grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
              <dt className="text-ink-muted">ID</dt>
              <dd className="break-all font-mono text-[11.5px]">
                <span className="select-all" title={tenant.id}>
                  {shortId(tenant)}
                </span>
              </dd>
              <dt className="text-ink-muted">Created</dt>
              <dd className="font-mono text-[11px] tabular-nums">
                <time dateTime={tenant.created_at}>{formatCreatedAt(tenant.created_at)}</time>
              </dd>
              <dt className="text-ink-muted">Limits</dt>
              <dd>
                <TenantLimitFacts tenant={tenant} variant="compact" />
              </dd>
              <dt className="text-ink-muted">Audit</dt>
              <dd>
                <AuditStatusBadge enabled={tenant.audit_enabled} />
              </dd>
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}

interface TenantsPaginationProps {
  total: number;
  offset: number;
  count: number;
  isFetching: boolean;
  onPrevious: () => void;
  onNext: () => void;
}

export function TenantsPagination({
  total,
  offset,
  count,
  isFetching,
  onPrevious,
  onNext,
}: TenantsPaginationProps) {
  if (total === 0) return null;

  const from = offset + 1;
  const to = offset + count;
  const hasPrevious = offset > 0;
  const hasNext = offset + count < total;

  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
      <p className="font-mono text-[11px] tabular-nums text-ink-muted">
        Showing {formatExactNumber(from)}–{formatExactNumber(to)} of {formatExactNumber(total)}
      </p>
      <div className="flex gap-2">
        <Button
          variant="secondary"
          onClick={onPrevious}
          disabled={!hasPrevious || isFetching}
          aria-label="Previous tenant page"
        >
          Previous
        </Button>
        <Button
          variant="secondary"
          onClick={onNext}
          disabled={!hasNext || isFetching}
          aria-label="Next tenant page"
        >
          Next
        </Button>
      </div>
    </div>
  );
}

export function TenantsSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading tenants…</span>
      <div aria-hidden="true" className="space-y-2">
        {[0, 1, 2, 3].map((row) => (
          <div
            key={row}
            className="grid grid-cols-[1.6fr_0.8fr_1.2fr_1fr_0.5fr] gap-4 rounded border border-line/70 px-3 py-3"
          >
            {[0, 1, 2, 3, 4].map((cell) => (
              <span
                key={cell}
                className="h-3 w-4/5 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none"
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function EmptyTenants() {
  return (
    <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
      <h4 className="text-sm font-semibold text-ink">No tenants yet</h4>
      <p className="mt-1 text-[13px] text-ink-muted">Create the first tenant above.</p>
    </div>
  );
}
