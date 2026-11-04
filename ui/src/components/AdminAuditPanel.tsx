import { useId, useMemo, useRef, useState, type FormEvent } from 'react';

import type { AdminActorType, AdminAuditEvent, AdminAuditQuery } from '../api/client';
import { useAdminAudit } from '../hooks/useAdminAudit';
import {
  ADMIN_AUDIT_ACTION_OPTIONS,
  ADMIN_AUDIT_TARGET_TYPES,
  adminAuditChanges,
} from '../lib/adminAudit';
import { formatCreatedAt, formatExactNumber } from '../lib/format';
import { Button } from './Button';
import { RefreshIcon } from './Icons';
import { Panel, PanelHeader } from './Panel';
import { RequestErrorPanel } from './RequestErrorPanel';

export const ADMIN_AUDIT_PAGE_SIZE = 25;

const FIELD_CLASS =
  'mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15';

interface FilterDraft {
  actorId: string;
  action: string;
  targetType: string;
  targetId: string;
  since: string;
  until: string;
}

const EMPTY_FILTERS: FilterDraft = {
  actorId: '',
  action: '',
  targetType: '',
  targetId: '',
  since: '',
  until: '',
};

function toIso(value: string): string | null {
  if (value.trim() === '') return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

function optional(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
}

const ACTOR_TYPE_LABELS: Record<AdminActorType, string> = {
  admin: 'Admin',
  master: 'Master key',
  bootstrap: 'Bootstrap',
};

const ACTOR_TYPE_STYLES: Record<AdminActorType, string> = {
  admin: 'border-line-strong bg-surface-sunken text-ink-muted',
  master: 'border-accent/25 bg-accent/10 text-accent',
  bootstrap: 'border-warn/30 bg-warn-soft text-warn',
};

export function AdminAuditPanel() {
  const [draft, setDraft] = useState<FilterDraft>(EMPTY_FILTERS);
  const [filters, setFilters] = useState<FilterDraft>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [rangeError, setRangeError] = useState<string | null>(null);
  const [timeError, setTimeError] = useState<string | null>(null);

  const actionListId = useId();
  const targetTypeId = useId();
  const actionId = useId();
  const targetIdField = useId();
  const actorIdField = useId();
  const sinceId = useId();
  const untilId = useId();
  const timeNoteId = useId();
  const timeErrorId = useId();
  const rangeErrorId = useId();
  const tableHeadingRef = useRef<HTMLHeadingElement>(null);

  const queryParams = useMemo<AdminAuditQuery>(() => {
    return {
      actorId: optional(filters.actorId),
      action: optional(filters.action),
      targetType: optional(filters.targetType),
      targetId: optional(filters.targetId),
      since: toIso(filters.since),
      until: toIso(filters.until),
      limit: ADMIN_AUDIT_PAGE_SIZE,
      offset,
    };
  }, [filters, offset]);

  const query = useAdminAudit(queryParams);

  const count =
    query.status === 'success'
      ? `${formatExactNumber(query.data.total)} ${query.data.total === 1 ? 'event' : 'events'}`
      : null;

  const updateDraft = (field: keyof FilterDraft, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }));
  };

  const handleApply = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const since = draft.since.trim() === '' ? null : toIso(draft.since);
    const until = draft.until.trim() === '' ? null : toIso(draft.until);
    const invalidTime =
      (draft.since.trim() !== '' && since === null) ||
      (draft.until.trim() !== '' && until === null);
    const invalidRange = since !== null && until !== null && since >= until;

    setTimeError(invalidTime ? 'Enter a valid date and time.' : null);
    setRangeError(invalidRange ? 'Since must be before until.' : null);
    if (invalidTime || invalidRange) return;

    setFilters(draft);
    setOffset(0);
    tableHeadingRef.current?.focus();
  };

  const handleClear = () => {
    setDraft(EMPTY_FILTERS);
    setFilters(EMPTY_FILTERS);
    setRangeError(null);
    setTimeError(null);
    setOffset(0);
  };

  const hasFilters =
    filters.actorId !== '' ||
    filters.action !== '' ||
    filters.targetType !== '' ||
    filters.targetId !== '' ||
    filters.since !== '' ||
    filters.until !== '';

  const draftHasValues =
    draft.actorId !== '' ||
    draft.action !== '' ||
    draft.targetType !== '' ||
    draft.targetId !== '' ||
    draft.since !== '' ||
    draft.until !== '';

  return (
    <Panel labelledBy="admin-audit-heading">
      <PanelHeader id="admin-audit-heading" eyebrow="History" title="Admin audit">
        <div className="flex items-center gap-2">
          {count !== null && (
            <span className="rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-ink">
              {count}
            </span>
          )}
          <Button
            variant="ghost"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
            aria-label="Refresh admin audit"
          >
            <RefreshIcon
              className={`size-3.5 ${query.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`}
            />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>
      </PanelHeader>

      <div className="px-5 py-4" aria-busy={query.isFetching}>
        <form onSubmit={handleApply} className="border-b border-line pb-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <div className="min-w-0">
              <label
                htmlFor={actionId}
                className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
              >
                Action
              </label>
              <input
                id={actionId}
                type="text"
                value={draft.action}
                onChange={(event) => updateDraft('action', event.target.value)}
                list={actionListId}
                placeholder="admin.updated"
                className={FIELD_CLASS}
              />
              <datalist id={actionListId}>
                {ADMIN_AUDIT_ACTION_OPTIONS.map((action) => (
                  <option key={action} value={action} />
                ))}
              </datalist>
            </div>

            <div className="min-w-0">
              <label
                htmlFor={targetTypeId}
                className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
              >
                Target type
              </label>
              <select
                id={targetTypeId}
                value={draft.targetType}
                onChange={(event) => updateDraft('targetType', event.target.value)}
                className={FIELD_CLASS}
              >
                <option value="">All target types</option>
                {ADMIN_AUDIT_TARGET_TYPES.map((target) => (
                  <option key={target} value={target}>
                    {target}
                  </option>
                ))}
              </select>
            </div>

            <div className="min-w-0">
              <label
                htmlFor={targetIdField}
                className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
              >
                Target ID
              </label>
              <input
                id={targetIdField}
                type="text"
                value={draft.targetId}
                onChange={(event) => updateDraft('targetId', event.target.value)}
                placeholder="Exact target id"
                className={FIELD_CLASS}
              />
            </div>

            <div className="min-w-0">
              <label
                htmlFor={actorIdField}
                className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
              >
                Actor ID
              </label>
              <input
                id={actorIdField}
                type="text"
                value={draft.actorId}
                onChange={(event) => updateDraft('actorId', event.target.value)}
                placeholder="Admin UUID"
                className={FIELD_CLASS}
              />
            </div>

            <div className="min-w-0">
              <label
                htmlFor={sinceId}
                className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
              >
                Since
              </label>
              <input
                id={sinceId}
                type="datetime-local"
                value={draft.since}
                onChange={(event) => updateDraft('since', event.target.value)}
                aria-describedby={timeError === null ? timeNoteId : `${timeNoteId} ${timeErrorId}`}
                className={FIELD_CLASS}
              />
            </div>

            <div className="min-w-0">
              <label
                htmlFor={untilId}
                className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
              >
                Until
              </label>
              <input
                id={untilId}
                type="datetime-local"
                value={draft.until}
                onChange={(event) => updateDraft('until', event.target.value)}
                aria-describedby={
                  rangeError === null ? timeNoteId : `${timeNoteId} ${rangeErrorId}`
                }
                className={FIELD_CLASS}
              />
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p id={timeNoteId} className="text-[11px] text-ink-muted">
                Times follow your browser timezone and are sent as UTC.
              </p>
              {timeError !== null && (
                <p id={timeErrorId} className="mt-1 text-[11px] text-danger">
                  {timeError}
                </p>
              )}
              {rangeError !== null && (
                <p id={rangeErrorId} className="mt-1 text-[11px] text-danger">
                  {rangeError}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              {(hasFilters || draftHasValues) && (
                <Button variant="ghost" onClick={handleClear}>
                  Clear filters
                </Button>
              )}
              <Button type="submit" variant="secondary">
                Apply filters
              </Button>
            </div>
          </div>
        </form>

        <p className="mt-3 rounded border border-line bg-surface-sunken/40 px-2.5 py-1.5 text-[11.5px] leading-5 text-ink-muted">
          Read-only history of management actions. Payloads carry business fields only; secrets,
          passwords, tokens, and key material are never shown.
        </p>

        <h3
          ref={tableHeadingRef}
          tabIndex={-1}
          className="mt-4 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted focus:outline-none"
        >
          Event directory
        </h3>

        <div className="mt-2">
          {query.isPending ? (
            <AdminAuditSkeleton />
          ) : query.isError ? (
            <RequestErrorPanel
              error={query.error}
              title="Could not load the admin audit trail"
              retryLabel="Retry loading the admin audit trail"
              onRetry={() => void query.refetch()}
            />
          ) : query.data.items.length === 0 ? (
            <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
              <h4 className="text-sm font-semibold text-ink">No admin events</h4>
              <p className="mt-1 text-[13px] text-ink-muted">
                {hasFilters
                  ? 'No event matches these filters.'
                  : 'Management actions will appear here as they happen.'}
              </p>
            </div>
          ) : (
            <>
              <AdminAuditTable events={query.data.items} />
              <AdminAuditPagination
                total={query.data.total}
                offset={query.data.offset}
                count={query.data.items.length}
                isFetching={query.isFetching}
                onPrevious={() =>
                  setOffset(Math.max(0, (query.data?.offset ?? offset) - ADMIN_AUDIT_PAGE_SIZE))
                }
                onNext={() => setOffset((query.data?.offset ?? offset) + ADMIN_AUDIT_PAGE_SIZE)}
              />
            </>
          )}
        </div>
      </div>
    </Panel>
  );
}

function ActorTypeBadge({ type }: { type: AdminActorType }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium ${ACTOR_TYPE_STYLES[type]}`}
    >
      {ACTOR_TYPE_LABELS[type]}
    </span>
  );
}

function ChangeList({
  before,
  after,
}: {
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}) {
  const changes = adminAuditChanges(before, after);
  if (changes.length === 0) {
    return <span className="font-mono text-[11px] text-ink-muted">—</span>;
  }

  return (
    <ul className="space-y-0.5">
      {changes.slice(0, 3).map((change) => (
        <li key={change.field} className="break-words font-mono text-[10.5px] leading-4 text-ink">
          <span className="text-ink-muted">{change.field}</span>
          {change.from !== null && change.to !== null ? (
            <>
              : {change.from} <span className="text-ink-muted">→</span> {change.to}
            </>
          ) : change.from === null ? (
            <> = {change.to}</>
          ) : (
            <>
              : {change.from} <span className="text-ink-muted">→ removed</span>
            </>
          )}
        </li>
      ))}
      {changes.length > 3 && (
        <li className="font-mono text-[10px] text-ink-muted">+{changes.length - 3} more</li>
      )}
    </ul>
  );
}

function Target({ event }: { event: AdminAuditEvent }) {
  return (
    <div className="min-w-0">
      <span className="inline-flex items-center rounded border border-line-strong bg-surface-sunken px-1.5 py-0.5 font-mono text-[10px] font-medium text-ink-muted">
        {event.target_type}
      </span>
      <span
        className="mt-1 block select-all break-all font-mono text-[10.5px] text-ink"
        title={event.target_id}
      >
        {event.target_id}
      </span>
    </div>
  );
}

function AdminAuditTable({ events }: { events: AdminAuditEvent[] }) {
  return (
    <>
      <div className="hidden lg:block">
        <table className="w-full table-fixed border-collapse text-left text-[13px]">
          <caption className="sr-only">Admin audit events</caption>
          <colgroup>
            <col className="w-[15%]" />
            <col className="w-[17%]" />
            <col className="w-[20%]" />
            <col className="w-[18%]" />
            <col className="w-[30%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-line">
              {['When (UTC)', 'Actor', 'Action', 'Target', 'Before / after'].map((label) => (
                <th
                  key={label}
                  scope="col"
                  className="py-2 pr-3 text-left font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted last:pr-0"
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {events.map((event) => (
              <tr key={event.id} className="transition-colors hover:bg-surface-sunken/40">
                <td className="py-2.5 pr-3 align-top font-mono text-[11px] tabular-nums">
                  <time dateTime={event.created_at}>{formatCreatedAt(event.created_at)}</time>
                </td>
                <td className="py-2.5 pr-3 align-top">
                  <span className="block break-words text-[12.5px] text-ink">
                    {event.actor_name}
                  </span>
                  <span className="mt-1 block">
                    <ActorTypeBadge type={event.actor_type} />
                  </span>
                </td>
                <td className="py-2.5 pr-3 align-top">
                  <span className="break-all font-mono text-[11px] text-ink">{event.action}</span>
                </td>
                <td className="py-2.5 pr-3 align-top">
                  <Target event={event} />
                </td>
                <td className="py-2.5 pr-3 align-top">
                  <ChangeList before={event.before} after={event.after} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul aria-label="Admin audit cards" className="divide-y divide-line lg:hidden">
        {events.map((event) => (
          <li key={event.id} className="py-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="break-all font-mono text-[11.5px] font-medium text-ink">
                  {event.action}
                </p>
                <p className="mt-0.5 font-mono text-[10.5px] tabular-nums text-ink-muted">
                  <time dateTime={event.created_at}>{formatCreatedAt(event.created_at)}</time>
                </p>
              </div>
              <ActorTypeBadge type={event.actor_type} />
            </div>
            <dl className="mt-2 grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
              <dt className="text-ink-muted">Actor</dt>
              <dd className="break-words text-ink">{event.actor_name}</dd>
              <dt className="text-ink-muted">Target</dt>
              <dd>
                <Target event={event} />
              </dd>
              <dt className="text-ink-muted">Changes</dt>
              <dd>
                <ChangeList before={event.before} after={event.after} />
              </dd>
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}

function AdminAuditPagination({
  total,
  offset,
  count,
  isFetching,
  onPrevious,
  onNext,
}: {
  total: number;
  offset: number;
  count: number;
  isFetching: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
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
          aria-label="Previous admin audit page"
        >
          Previous
        </Button>
        <Button
          variant="secondary"
          onClick={onNext}
          disabled={!hasNext || isFetching}
          aria-label="Next admin audit page"
        >
          Next
        </Button>
      </div>
    </div>
  );
}

function AdminAuditSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading admin audit…</span>
      <div aria-hidden="true" className="space-y-2">
        {[0, 1, 2, 3].map((row) => (
          <div
            key={row}
            className="grid grid-cols-[0.9fr_1fr_1.1fr_1fr_1.6fr] gap-4 rounded border border-line/70 px-3 py-3"
          >
            {[0, 1, 2, 3, 4].map((cell) => (
              <span
                key={cell}
                className="h-3.5 w-4/5 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none"
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
