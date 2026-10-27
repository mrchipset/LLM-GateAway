import type { AuditSessionSummary } from '../api/client';
import { auditSessionTitle, shortIdentifier } from '../lib/audit';
import {
  formatCreatedAt,
  formatCreatedDate,
  formatCreatedTime,
  formatExactNumber,
} from '../lib/format';
import { Button } from './Button';
import { CompactNumber } from './CompactNumber';

interface AuditSessionsTableProps {
  sessions: AuditSessionSummary[];
  tenantNames: ReadonlyMap<string, string>;
  onOpen: (session: AuditSessionSummary) => void;
}

function StackedTimestamp({ value, className }: { value: string; className: string }) {
  return (
    <time
      dateTime={value}
      title={formatCreatedAt(value)}
      className={`block whitespace-nowrap font-mono tabular-nums ${className}`}
    >
      {formatCreatedDate(value)}, <br />
      {formatCreatedTime(value)} UTC
    </time>
  );
}

function SessionTitleButton({
  session,
  onOpen,
}: {
  session: AuditSessionSummary;
  onOpen: AuditSessionsTableProps['onOpen'];
}) {
  const title = auditSessionTitle(session.title_preview);
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        onOpen(session);
      }}
      aria-label={`Open session ${title}`}
      data-audit-session-open={session.id}
      className="block max-w-full text-left font-medium leading-snug break-words text-ink transition-colors hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      {title}
    </button>
  );
}

function TenantCell({
  session,
  tenantNames,
}: {
  session: AuditSessionSummary;
  tenantNames: ReadonlyMap<string, string>;
}) {
  const name = tenantNames.get(session.tenant_id);
  return (
    <>
      {name !== undefined ? (
        <>
          <span className="block break-words text-[12px] text-ink">{name}</span>
          <span
            className="mt-0.5 block select-all font-mono text-[10.5px] text-ink-muted"
            title={session.tenant_id}
          >
            {shortIdentifier(session.tenant_id)}
          </span>
        </>
      ) : (
        <span
          className="block select-all break-all font-mono text-[11px] text-ink"
          title={session.tenant_id}
        >
          {shortIdentifier(session.tenant_id)}
        </span>
      )}
    </>
  );
}

export function AuditSessionsTable({ sessions, tenantNames, onOpen }: AuditSessionsTableProps) {
  return (
    <>
      <div className="hidden md:block">
        <table className="w-full table-fixed border-collapse text-left text-[12.5px]">
          <caption className="sr-only">Audited sessions</caption>
          <colgroup>
            <col className="w-[26%]" />
            <col className="w-[16%]" />
            <col className="w-[14%]" />
            <col className="w-[15%]" />
            <col className="w-[8%]" />
            <col className="w-[13%]" />
            <col className="w-[8%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-line">
              {[
                'Session',
                'Tenant',
                'Key',
                'Model',
                'Requests',
                'Last activity (UTC)',
                'Tokens',
              ].map((label, index) => (
                <th
                  key={label}
                  scope="col"
                  className={`py-2 pr-3 font-mono text-[10px] font-medium uppercase tracking-[0.1em] text-ink-muted last:pr-0 ${
                    index >= 4 ? 'text-right' : 'text-left'
                  }`}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {sessions.map((session) => (
              <tr
                key={session.id}
                onClick={() => onOpen(session)}
                className="cursor-pointer transition-colors hover:bg-surface-sunken/40"
              >
                <th scope="row" className="py-3 pr-3 align-top">
                  <SessionTitleButton session={session} onOpen={onOpen} />
                  <span
                    className="mt-0.5 block select-all font-mono text-[10.5px] text-ink-muted"
                    title={session.id}
                  >
                    {shortIdentifier(session.id)}
                  </span>
                </th>
                <td className="py-3 pr-3 align-top">
                  <TenantCell session={session} tenantNames={tenantNames} />
                </td>
                <td className="py-3 pr-3 align-top">
                  <span
                    className="block select-all break-all font-mono text-[10.5px] text-ink"
                    title={session.api_key_prefix}
                  >
                    {session.api_key_prefix}
                  </span>
                </td>
                <td className="py-3 pr-3 align-top">
                  <span className="block break-all font-mono text-[11px] text-ink">
                    {session.model_id}
                  </span>
                  <span className="mt-0.5 block break-words text-[10.5px] text-ink-muted">
                    {session.provider}
                  </span>
                </td>
                <td className="py-3 pr-3 text-right align-top font-mono text-[11.5px] tabular-nums">
                  {formatExactNumber(session.request_count)}
                </td>
                <td className="py-3 pr-3 text-right align-top">
                  <StackedTimestamp
                    value={session.last_seen_at}
                    className="text-[10.5px] text-ink-muted"
                  />
                </td>
                <td className="py-3 text-right align-top font-mono text-[11.5px]">
                  <CompactNumber value={session.total_tokens} unit="tokens" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul aria-label="Audited session cards" className="divide-y divide-line md:hidden">
        {sessions.map((session) => (
          <li
            key={session.id}
            onClick={() => onOpen(session)}
            className="cursor-pointer py-3 transition-colors hover:bg-surface-sunken/40"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <SessionTitleButton session={session} onOpen={onOpen} />
                <span
                  className="mt-0.5 block select-all font-mono text-[10.5px] text-ink-muted"
                  title={session.id}
                >
                  {shortIdentifier(session.id)}
                </span>
              </div>
              <span className="shrink-0 rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-ink">
                {formatExactNumber(session.request_count)} req
              </span>
            </div>
            <dl className="mt-2 grid grid-cols-[5.75rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
              <dt className="text-ink-muted">Tenant</dt>
              <dd>
                <TenantCell session={session} tenantNames={tenantNames} />
              </dd>
              <dt className="text-ink-muted">Key</dt>
              <dd className="break-all font-mono text-[11px]">
                <span className="select-all" title={session.api_key_prefix}>
                  {session.api_key_prefix}
                </span>
              </dd>
              <dt className="text-ink-muted">Model</dt>
              <dd className="break-words">
                <span className="font-mono text-[11px]">{session.model_id}</span>
                <span className="text-ink-muted"> · {session.provider}</span>
              </dd>
              <dt className="text-ink-muted">Last activity</dt>
              <dd className="font-mono text-[11px] tabular-nums">
                <time dateTime={session.last_seen_at}>{formatCreatedAt(session.last_seen_at)}</time>
              </dd>
              <dt className="text-ink-muted">Tokens</dt>
              <dd className="text-right font-mono text-[11px]">
                <CompactNumber value={session.total_tokens} unit="tokens" />
              </dd>
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}

interface AuditPaginationProps {
  total: number;
  offset: number;
  count: number;
  isFetching: boolean;
  onPrevious: () => void;
  onNext: () => void;
}

export function AuditPagination({
  total,
  offset,
  count,
  isFetching,
  onPrevious,
  onNext,
}: AuditPaginationProps) {
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
          aria-label="Previous audit page"
        >
          Previous
        </Button>
        <Button
          variant="secondary"
          onClick={onNext}
          disabled={!hasNext || isFetching}
          aria-label="Next audit page"
        >
          Next
        </Button>
      </div>
    </div>
  );
}

export function AuditSessionsSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading audited sessions…</span>
      <div aria-hidden="true" className="space-y-2">
        {[0, 1, 2, 3].map((row) => (
          <div
            key={row}
            className="grid grid-cols-[1.6fr_1fr_0.9fr_0.9fr_0.5fr_0.9fr_0.5fr] gap-3 rounded border border-line/70 px-3 py-3"
          >
            {[0, 1, 2, 3, 4, 5, 6].map((cell) => (
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

export function EmptyAuditSessions() {
  return (
    <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
      <h4 className="text-sm font-semibold text-ink">No audited sessions</h4>
      <p className="mx-auto mt-1 max-w-lg text-[13px] text-ink-muted">
        No sessions match these filters in the selected window. Audit collection must be enabled
        globally and for the tenant, and only opted-in requests are captured.
      </p>
    </div>
  );
}
