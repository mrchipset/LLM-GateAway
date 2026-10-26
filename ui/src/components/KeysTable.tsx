import type { ApiKeySummary } from '../api/client';
import { formatCreatedAt, formatExactNumber } from '../lib/format';
import { apiKeyStatus, type KeyStatus } from '../lib/keys';
import { Button } from './Button';
import { TrashIcon } from './Icons';

const STATUS_CLASSES: Record<KeyStatus, string> = {
  Active: 'border-ok/25 bg-ok-soft text-ok',
  Revoked: 'border-danger/25 bg-danger-soft text-danger',
  Expired: 'border-warn/30 bg-warn-soft text-warn',
};

function tenantLabel(tenantId: string, tenantNames: ReadonlyMap<string, string>): string {
  const name = tenantNames.get(tenantId);
  if (name !== undefined) return name;
  return `${tenantId.slice(0, 8)}…`;
}

function StatusBadge({ status }: { status: KeyStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10.5px] font-medium ${STATUS_CLASSES[status]}`}
    >
      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

interface RevokeButtonProps {
  apiKey: ApiKeySummary;
  onRevoke: KeysTableProps['onRevoke'];
  withLabel?: boolean;
}

function RevokeButton({ apiKey, onRevoke, withLabel = false }: RevokeButtonProps) {
  return (
    <Button
      variant="ghost"
      onClick={(event) => onRevoke(apiKey, event.currentTarget)}
      aria-label={`Revoke ${apiKey.name}`}
      title="Revoke key"
      className="shrink-0 px-2 py-1 text-[12px] text-danger hover:bg-danger-soft hover:text-danger"
    >
      <TrashIcon className="size-3.5" />
      {withLabel && <span>Revoke</span>}
    </Button>
  );
}

interface KeysTableProps {
  keys: ApiKeySummary[];
  tenantNames: ReadonlyMap<string, string>;
  now: number;
  onRevoke: (apiKey: ApiKeySummary, trigger: HTMLButtonElement) => void;
}

export function KeysTable({ keys, tenantNames, now, onRevoke }: KeysTableProps) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[44rem] table-fixed border-collapse text-left text-[12.5px]">
          <caption className="sr-only">API keys</caption>
          <colgroup>
            <col className="w-[16%]" />
            <col className="w-[13%]" />
            <col className="w-[13%]" />
            <col className="w-[15%]" />
            <col className="w-[15%]" />
            <col className="w-[9%]" />
            <col className="w-[12%]" />
            <col className="w-[7%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-line">
              {[
                'Name',
                'Prefix',
                'Tenant',
                'Created (UTC)',
                'Expires (UTC)',
                'Status',
                'Last used (UTC)',
                'Action',
              ].map((label, index) => (
                <th
                  key={label}
                  scope="col"
                  className={`py-2 pr-2.5 font-mono text-[10px] font-medium uppercase tracking-[0.1em] text-ink-muted last:pr-0 ${
                    index === 7 ? 'text-right' : 'text-left'
                  }`}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {keys.map((apiKey) => {
              const status = apiKeyStatus(apiKey, now);
              return (
                <tr key={apiKey.id} className="transition-colors hover:bg-surface-sunken/40">
                  <th
                    scope="row"
                    className="break-words py-2.5 pr-2.5 align-top font-medium text-ink"
                  >
                    {apiKey.name}
                  </th>
                  <td className="py-2.5 pr-2.5 align-top">
                    <span
                      className="select-all break-all font-mono text-[11px] text-ink"
                      title={apiKey.key_prefix}
                    >
                      {apiKey.key_prefix}
                    </span>
                  </td>
                  <td className="py-2.5 pr-2.5 align-top">
                    <span className="break-words" title={apiKey.tenant_id}>
                      {tenantLabel(apiKey.tenant_id, tenantNames)}
                    </span>
                  </td>
                  <td className="py-2.5 pr-2.5 align-top font-mono text-[11px] tabular-nums">
                    <time dateTime={apiKey.created_at}>{formatCreatedAt(apiKey.created_at)}</time>
                  </td>
                  <td className="py-2.5 pr-2.5 align-top font-mono text-[11px] tabular-nums">
                    {apiKey.expires_at === null ? (
                      '—'
                    ) : (
                      <time dateTime={apiKey.expires_at}>{formatCreatedAt(apiKey.expires_at)}</time>
                    )}
                  </td>
                  <td className="py-2.5 pr-2.5 align-top">
                    <StatusBadge status={status} />
                  </td>
                  <td className="py-2.5 pr-2.5 align-top font-mono text-[11px] tabular-nums">
                    {apiKey.last_used_at === null ? (
                      '—'
                    ) : (
                      <time dateTime={apiKey.last_used_at}>
                        {formatCreatedAt(apiKey.last_used_at)}
                      </time>
                    )}
                  </td>
                  <td className="py-2.5 text-right align-top">
                    {status !== 'Revoked' && <RevokeButton apiKey={apiKey} onRevoke={onRevoke} />}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ul aria-label="API key cards" className="divide-y divide-line md:hidden">
        {keys.map((apiKey) => {
          const status = apiKeyStatus(apiKey, now);
          return (
            <li key={apiKey.id} className="py-3">
              <div className="flex items-start justify-between gap-3">
                <p className="break-words font-medium text-ink">{apiKey.name}</p>
                <StatusBadge status={status} />
              </div>
              <dl className="mt-2 grid grid-cols-[5.75rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
                <dt className="text-ink-muted">Prefix</dt>
                <dd className="break-all font-mono text-[11px]">
                  <span className="select-all" title={apiKey.key_prefix}>
                    {apiKey.key_prefix}
                  </span>
                </dd>
                <dt className="text-ink-muted">Tenant</dt>
                <dd className="break-words" title={apiKey.tenant_id}>
                  {tenantLabel(apiKey.tenant_id, tenantNames)}
                </dd>
                <dt className="text-ink-muted">Created</dt>
                <dd className="font-mono text-[11px] tabular-nums">
                  <time dateTime={apiKey.created_at}>{formatCreatedAt(apiKey.created_at)}</time>
                </dd>
                <dt className="text-ink-muted">Expires</dt>
                <dd className="font-mono text-[11px] tabular-nums">
                  {apiKey.expires_at === null ? (
                    '—'
                  ) : (
                    <time dateTime={apiKey.expires_at}>{formatCreatedAt(apiKey.expires_at)}</time>
                  )}
                </dd>
                <dt className="text-ink-muted">Last used</dt>
                <dd className="font-mono text-[11px] tabular-nums">
                  {apiKey.last_used_at === null ? (
                    '—'
                  ) : (
                    <time dateTime={apiKey.last_used_at}>
                      {formatCreatedAt(apiKey.last_used_at)}
                    </time>
                  )}
                </dd>
              </dl>
              {status !== 'Revoked' && (
                <div className="mt-2 flex justify-end">
                  <RevokeButton apiKey={apiKey} onRevoke={onRevoke} withLabel />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

interface KeysPaginationProps {
  total: number;
  offset: number;
  count: number;
  isFetching: boolean;
  onPrevious: () => void;
  onNext: () => void;
}

export function KeysPagination({
  total,
  offset,
  count,
  isFetching,
  onPrevious,
  onNext,
}: KeysPaginationProps) {
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
          aria-label="Previous key page"
        >
          Previous
        </Button>
        <Button
          variant="secondary"
          onClick={onNext}
          disabled={!hasNext || isFetching}
          aria-label="Next key page"
        >
          Next
        </Button>
      </div>
    </div>
  );
}

export function KeysSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading API keys…</span>
      <div aria-hidden="true" className="space-y-2">
        {[0, 1, 2, 3].map((row) => (
          <div
            key={row}
            className="grid grid-cols-[1.4fr_1fr_1fr_1.2fr_1.2fr_0.7fr_1fr_0.4fr] gap-3 rounded border border-line/70 px-3 py-3"
          >
            {[0, 1, 2, 3, 4, 5, 6, 7].map((cell) => (
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

interface EmptyKeysProps {
  createDisabled: boolean;
  onCreate: () => void;
}

export function EmptyKeys({ createDisabled, onCreate }: EmptyKeysProps) {
  return (
    <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
      <h4 className="text-sm font-semibold text-ink">No API keys</h4>
      <p className="mt-1 text-[13px] text-ink-muted">
        Create an API key to let a client call the gateway.
      </p>
      <Button onClick={onCreate} disabled={createDisabled} className="mt-3">
        Create your first API key
      </Button>
    </div>
  );
}
