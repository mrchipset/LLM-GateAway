import { useId, type ReactNode } from 'react';

import type { TenantSummary } from '../api/client';
import type { TenantsQuery } from '../hooks/useTenants';
import type { UsageByKeyQuery, UsageSeriesQuery, UsageSummaryQuery } from '../hooks/useUsage';
import { formatCompactNumber, formatExactNumber, formatUpdatedAt } from '../lib/format';
import { USAGE_RANGE_PRESETS, type UsageRangeDays } from '../lib/usage';
import { Button } from './Button';
import { KeyIcon, RefreshIcon } from './Icons';
import { Panel, PanelHeader } from './Panel';
import { RequestErrorPanel } from './RequestErrorPanel';
import { TenantLimitFacts } from './TenantLimitFacts';
import { UsageByKeyTable, UsageTableSkeleton } from './UsageByKeyTable';
import { UsageChart } from './UsageChart';
import { UsageStats, UsageStatsSkeleton } from './UsageStats';

interface UsagePanelProps {
  masterKey: string | null;
  tenantId: string;
  rangeDays: UsageRangeDays;
  onTenantChange: (tenantId: string) => void;
  onRangeChange: (days: UsageRangeDays) => void;
  onRefresh: () => void;
  tenantsQuery: TenantsQuery;
  summaryQuery: UsageSummaryQuery;
  seriesQuery: UsageSeriesQuery;
  byKeyQuery: UsageByKeyQuery;
}

export function UsagePanel({
  masterKey,
  tenantId,
  rangeDays,
  onTenantChange,
  onRangeChange,
  onRefresh,
  tenantsQuery,
  summaryQuery,
  seriesQuery,
  byKeyQuery,
}: UsagePanelProps) {
  const isRefreshing =
    tenantsQuery.isFetching ||
    summaryQuery.isFetching ||
    seriesQuery.isFetching ||
    byKeyQuery.isFetching;

  return (
    <Panel labelledBy="usage-heading">
      <PanelHeader id="usage-heading" eyebrow="Telemetry" title="Usage">
        {masterKey !== null && (
          <Button
            variant="ghost"
            onClick={onRefresh}
            disabled={isRefreshing}
            aria-label="Refresh usage"
          >
            <RefreshIcon
              className={`size-3.5 ${isRefreshing ? 'animate-spin motion-reduce:animate-none' : ''}`}
            />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        )}
      </PanelHeader>
      <div className="px-5 py-4" aria-busy={masterKey !== null && isRefreshing}>
        {masterKey === null ? (
          <UsageConnectPrompt />
        ) : (
          <UsageContent
            tenantId={tenantId}
            rangeDays={rangeDays}
            onTenantChange={onTenantChange}
            onRangeChange={onRangeChange}
            tenantsQuery={tenantsQuery}
            summaryQuery={summaryQuery}
            seriesQuery={seriesQuery}
            byKeyQuery={byKeyQuery}
          />
        )}
      </div>
    </Panel>
  );
}

type UsageContentProps = Omit<UsagePanelProps, 'masterKey' | 'onRefresh'>;

function UsageContent({
  tenantId,
  rangeDays,
  onTenantChange,
  onRangeChange,
  tenantsQuery,
  summaryQuery,
  seriesQuery,
  byKeyQuery,
}: UsageContentProps) {
  const tenantSelectId = useId();
  const rangeLabelId = useId();
  const totalsHeadingId = useId();
  const chartHeadingId = useId();
  const byKeyHeadingId = useId();

  const selectedTenant = tenantsQuery.data?.items.find((tenant) => tenant.id === tenantId) ?? null;
  const updatedAt = Math.max(
    summaryQuery.dataUpdatedAt,
    seriesQuery.dataUpdatedAt,
    byKeyQuery.dataUpdatedAt,
  );
  const peak = seriesQuery.data?.points.reduce(
    (max, point) => Math.max(max, point.total_tokens),
    0,
  );

  return (
    <>
      <UsageControls
        tenantId={tenantId}
        rangeDays={rangeDays}
        onTenantChange={onTenantChange}
        onRangeChange={onRangeChange}
        tenantsQuery={tenantsQuery}
        selectedTenant={selectedTenant}
        updatedAt={updatedAt}
        tenantSelectId={tenantSelectId}
        rangeLabelId={rangeLabelId}
      />

      <div className="mt-4 space-y-5">
        <section aria-labelledby={totalsHeadingId}>
          <SectionHeading id={totalsHeadingId}>Window totals</SectionHeading>
          <div className="mt-2">
            {summaryQuery.isPending ? (
              <UsageStatsSkeleton />
            ) : summaryQuery.isError ? (
              <RequestErrorPanel
                error={summaryQuery.error}
                title="Could not load usage totals"
                retryLabel="Retry loading usage totals"
                onRetry={() => void summaryQuery.refetch()}
              />
            ) : (
              <UsageStats summary={summaryQuery.data} />
            )}
          </div>
        </section>

        <section aria-labelledby={chartHeadingId}>
          <SectionHeading
            id={chartHeadingId}
            aside={
              seriesQuery.status === 'success' ? (
                <span>UTC · Peak {formatCompactNumber(peak ?? 0)}</span>
              ) : null
            }
          >
            Daily total tokens
          </SectionHeading>
          <div className="mt-2">
            {seriesQuery.isPending ? (
              <ChartSkeleton />
            ) : seriesQuery.isError ? (
              <RequestErrorPanel
                error={seriesQuery.error}
                title="Could not load the usage chart"
                retryLabel="Retry loading the usage chart"
                onRetry={() => void seriesQuery.refetch()}
              />
            ) : seriesQuery.data.points.length === 0 ? (
              <EmptyRange />
            ) : (
              <UsageChart points={seriesQuery.data.points} />
            )}
          </div>
        </section>

        <section aria-labelledby={byKeyHeadingId}>
          <SectionHeading
            id={byKeyHeadingId}
            aside={
              byKeyQuery.status === 'success' && byKeyQuery.data.items.length > 0 ? (
                <span>
                  {byKeyQuery.data.items.length}{' '}
                  {byKeyQuery.data.items.length === 1 ? 'key' : 'keys'}
                </span>
              ) : null
            }
          >
            Usage by key
          </SectionHeading>
          <div className="mt-2">
            {byKeyQuery.isPending ? (
              <UsageTableSkeleton />
            ) : byKeyQuery.isError ? (
              <RequestErrorPanel
                error={byKeyQuery.error}
                title="Could not load usage by key"
                retryLabel="Retry loading usage by key"
                onRetry={() => void byKeyQuery.refetch()}
              />
            ) : (
              <UsageByKeyTable items={byKeyQuery.data.items} limit={byKeyQuery.data.limit} />
            )}
          </div>
        </section>
      </div>
    </>
  );
}

interface UsageControlsProps {
  tenantId: string;
  rangeDays: UsageRangeDays;
  onTenantChange: (tenantId: string) => void;
  onRangeChange: (days: UsageRangeDays) => void;
  tenantsQuery: TenantsQuery;
  selectedTenant: TenantSummary | null;
  updatedAt: number;
  tenantSelectId: string;
  rangeLabelId: string;
}

function UsageControls({
  tenantId,
  rangeDays,
  onTenantChange,
  onRangeChange,
  tenantsQuery,
  selectedTenant,
  updatedAt,
  tenantSelectId,
  rangeLabelId,
}: UsageControlsProps) {
  const tenantNoteId = useId();
  const tenantsData = tenantsQuery.data;
  const tenantCountNote =
    tenantsData !== undefined && tenantsData.total > tenantsData.items.length
      ? `Showing ${formatExactNumber(tenantsData.items.length)} of ${formatExactNumber(
          tenantsData.total,
        )} tenants`
      : null;

  return (
    <div className="border-b border-line pb-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[11rem]">
            <label
              htmlFor={tenantSelectId}
              className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
            >
              Tenant
            </label>
            <select
              id={tenantSelectId}
              value={tenantId}
              onChange={(event) => onTenantChange(event.target.value)}
              disabled={tenantsQuery.isPending}
              aria-describedby={tenantCountNote !== null ? tenantNoteId : undefined}
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[12.5px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            >
              <option value="">All tenants</option>
              {tenantsQuery.data?.items.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.name}
                </option>
              ))}
            </select>
            {tenantCountNote !== null && (
              <p
                id={tenantNoteId}
                className="mt-1 font-mono text-[10px] tabular-nums text-ink-muted"
              >
                {tenantCountNote}
              </p>
            )}
          </div>

          <div>
            <p
              id={rangeLabelId}
              className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
            >
              Range
            </p>
            <div
              role="group"
              aria-labelledby={rangeLabelId}
              className="mt-1 inline-flex rounded-md border border-line bg-surface-sunken p-0.5"
            >
              {USAGE_RANGE_PRESETS.map((preset) => {
                const selected = rangeDays === preset.days;
                return (
                  <button
                    key={preset.days}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => onRangeChange(preset.days)}
                    className={`rounded px-2.5 py-1 font-mono text-[11px] tabular-nums transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                      selected
                        ? 'bg-surface text-ink shadow-[0_1px_2px_rgba(22,24,26,0.08)]'
                        : 'text-ink-muted hover:text-ink'
                    }`}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div className="flex items-baseline gap-2 lg:flex-col lg:items-end lg:gap-0.5">
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted">
            Last updated
          </p>
          {updatedAt > 0 ? (
            <time
              dateTime={new Date(updatedAt).toISOString()}
              className="font-mono text-[11px] tabular-nums text-ink"
            >
              {formatUpdatedAt(updatedAt)}
            </time>
          ) : (
            <span className="font-mono text-[11px] text-ink-muted">—</span>
          )}
        </div>
      </div>

      <div
        role="group"
        aria-label="Tenant limits"
        aria-live="polite"
        className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1.5 rounded-md border border-line bg-surface-sunken/50 px-2.5 py-1.5"
      >
        <span className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted">
          Limits
        </span>
        {selectedTenant !== null ? (
          <TenantLimitFacts tenant={selectedTenant} />
        ) : (
          <span className="text-[11.5px] text-ink-muted">Select a tenant to see its limits.</span>
        )}
      </div>

      {tenantsQuery.isError && (
        <div className="mt-3">
          <RequestErrorPanel
            error={tenantsQuery.error}
            title="Could not load tenants"
            retryLabel="Retry loading tenants"
            onRetry={() => void tenantsQuery.refetch()}
          />
        </div>
      )}
    </div>
  );
}

interface SectionHeadingProps {
  id: string;
  children: ReactNode;
  aside?: ReactNode;
}

function SectionHeading({ id, children, aside }: SectionHeadingProps) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h3
        id={id}
        className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted"
      >
        {children}
      </h3>
      {aside !== null && aside !== undefined && (
        <p className="font-mono text-[10px] tabular-nums text-ink-muted">{aside}</p>
      )}
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading usage chart…</span>
      <div
        aria-hidden="true"
        className="h-36 animate-pulse rounded-md border border-line bg-surface-sunken/50 motion-reduce:animate-none sm:h-40"
      />
      <div aria-hidden="true" className="mt-2 flex justify-between">
        <span className="h-2.5 w-12 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
        <span className="h-2.5 w-12 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
        <span className="h-2.5 w-12 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
      </div>
    </div>
  );
}

function EmptyRange() {
  return (
    <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
      <p className="text-[13px] text-ink-muted">No usage in this range.</p>
    </div>
  );
}

function UsageConnectPrompt() {
  return (
    <div className="flex min-h-40 flex-col items-start justify-center gap-1.5 py-4">
      <KeyIcon className="size-5 text-ink-muted" />
      <p className="mt-1 text-sm font-medium text-ink">Connect a master key to load usage.</p>
      <p className="max-w-md text-[13px] text-ink-muted">
        The key is sent only to the management API from this browser tab.
      </p>
    </div>
  );
}
