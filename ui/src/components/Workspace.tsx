import { useMemo, useRef, useState, type KeyboardEvent, type ReactElement } from 'react';

import { useModels } from '../hooks/useModels';
import { useTenants } from '../hooks/useTenants';
import { useUsageByKey, useUsageSeries, useUsageSummary } from '../hooks/useUsage';
import { formatUpdatedAt } from '../lib/format';
import { DEFAULT_USAGE_RANGE_DAYS, usageRangeSinceIso, type UsageRangeDays } from '../lib/usage';
import {
  AccessIcon,
  AdminAuditIcon,
  AdminsIcon,
  AuditIcon,
  LockIcon,
  ModelsIcon,
  UsageIcon,
} from './Icons';
import { AccessPanel } from './AccessPanel';
import { AdminAuditPanel } from './AdminAuditPanel';
import { AdminsPanel } from './AdminsPanel';
import { AuditPanel } from './AuditPanel';
import { ModelsPanel } from './ModelsPanel';
import { useAdminSession } from '../lib/adminSessionContext';
import { UsagePanel } from './UsagePanel';

interface TabItem {
  id: WorkspaceTab;
  label: string;
  Icon: (props: { className?: string }) => ReactElement;
}

type WorkspaceTab = 'models' | 'usage' | 'access' | 'audit' | 'admins' | 'admin-audit';

export function Workspace() {
  const { canManageAdmins, canReadAudit, canWrite } = useAdminSession();
  const [tab, setTab] = useState<WorkspaceTab>('models');
  const [tenantId, setTenantId] = useState('');
  const [rangeDays, setRangeDays] = useState<UsageRangeDays>(DEFAULT_USAGE_RANGE_DAYS);
  const [anchor, setAnchor] = useState(() => new Date());
  const tabRefs = useRef<Partial<Record<WorkspaceTab, HTMLButtonElement | null>>>({});

  const tabs: TabItem[] = [
    { id: 'models', label: 'Models', Icon: ModelsIcon },
    { id: 'usage', label: 'Usage', Icon: UsageIcon },
    { id: 'access', label: 'Access', Icon: AccessIcon },
    ...(canReadAudit ? [{ id: 'audit' as const, label: 'Audit', Icon: AuditIcon }] : []),
    ...(canManageAdmins ? [{ id: 'admins' as const, label: 'Admins', Icon: AdminsIcon }] : []),
    ...(canReadAudit
      ? [{ id: 'admin-audit' as const, label: 'Admin audit', Icon: AdminAuditIcon }]
      : []),
  ];

  const since = useMemo(() => usageRangeSinceIso(rangeDays, anchor), [rangeDays, anchor]);
  const usageWindow = useMemo(
    () => ({ tenantId: tenantId === '' ? null : tenantId, since }),
    [tenantId, since],
  );

  const modelsQuery = useModels();
  const tenantsQuery = useTenants();
  const summaryQuery = useUsageSummary(usageWindow);
  const seriesQuery = useUsageSeries(usageWindow);
  const byKeyQuery = useUsageByKey(usageWindow);

  const usageUpdatedAt = Math.max(
    summaryQuery.dataUpdatedAt,
    seriesQuery.dataUpdatedAt,
    byKeyQuery.dataUpdatedAt,
  );
  const usageHasError = summaryQuery.isError || seriesQuery.isError || byKeyQuery.isError;
  const usageSettled =
    summaryQuery.status === 'success' &&
    seriesQuery.status === 'success' &&
    byKeyQuery.status === 'success' &&
    !summaryQuery.isFetching &&
    !seriesQuery.isFetching &&
    !byKeyQuery.isFetching;

  const announcement =
    !usageHasError && usageSettled && usageUpdatedAt > 0
      ? `Usage updated at ${formatUpdatedAt(usageUpdatedAt)} for the last ${rangeDays} days.`
      : '';

  const handleRangeChange = (days: UsageRangeDays) => {
    setRangeDays(days);
    setAnchor(new Date());
  };

  const handleRefresh = () => {
    const nextAnchor = new Date();
    const nextSince = usageRangeSinceIso(rangeDays, nextAnchor);
    setAnchor(nextAnchor);

    if (nextSince === since) {
      void Promise.all([
        summaryQuery.refetch(),
        seriesQuery.refetch(),
        byKeyQuery.refetch(),
        tenantsQuery.refetch(),
      ]);
      return;
    }

    void tenantsQuery.refetch();
  };

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const currentIndex = tabs.findIndex((item) => item.id === tab);
    if (currentIndex === -1) return;

    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % tabs.length;
    if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = tabs.length - 1;
    if (nextIndex === null) return;

    const nextTab = tabs[nextIndex];
    if (nextTab === undefined) return;

    event.preventDefault();
    setTab(nextTab.id);
    tabRefs.current[nextTab.id]?.focus();
  };

  return (
    <div>
      <div className="mb-3 max-w-full overflow-x-auto">
        <div
          role="tablist"
          aria-label="Admin sections"
          className="inline-flex min-w-max rounded-md border border-line bg-surface-sunken p-0.5"
        >
          {tabs.map((item) => {
            const active = tab === item.id;
            const Icon = item.Icon;
            return (
              <button
                key={item.id}
                ref={(element) => {
                  tabRefs.current[item.id] = element;
                }}
                id={`${item.id}-tab`}
                type="button"
                role="tab"
                aria-selected={active}
                aria-controls={`${item.id}-panel`}
                tabIndex={active ? 0 : -1}
                onClick={() => setTab(item.id)}
                onKeyDown={handleTabKeyDown}
                className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded px-3 py-1.5 text-[12px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                  active
                    ? 'bg-surface text-ink shadow-[0_1px_2px_rgba(22,24,26,0.08)]'
                    : 'text-ink-muted hover:bg-surface/60 hover:text-ink'
                }`}
              >
                <Icon className={`size-3.5 ${active ? 'text-accent' : ''}`} />
                {item.label}
              </button>
            );
          })}
        </div>
      </div>

      {!canWrite && (
        <p className="mb-4 flex flex-wrap items-center gap-2 rounded border border-line bg-surface-sunken/60 px-2.5 py-1.5 text-[11.5px] leading-5 text-ink-muted">
          <LockIcon className="size-3.5 shrink-0 text-ink-muted" />
          <span>
            <span className="font-medium text-ink">Read-only role.</span> Create, edit, revoke, and
            pricing controls are hidden.
          </span>
        </p>
      )}

      {announcement !== '' && (
        <p role="status" className="sr-only">
          {announcement}
        </p>
      )}

      <div
        role="tabpanel"
        id="models-panel"
        aria-labelledby="models-tab"
        hidden={tab !== 'models'}
        className="min-w-0"
      >
        <ModelsPanel query={modelsQuery} />
      </div>

      <div
        role="tabpanel"
        id="usage-panel"
        aria-labelledby="usage-tab"
        hidden={tab !== 'usage'}
        className="min-w-0"
      >
        <UsagePanel
          tenantId={tenantId}
          rangeDays={rangeDays}
          onTenantChange={setTenantId}
          onRangeChange={handleRangeChange}
          onRefresh={handleRefresh}
          tenantsQuery={tenantsQuery}
          summaryQuery={summaryQuery}
          seriesQuery={seriesQuery}
          byKeyQuery={byKeyQuery}
        />
      </div>

      <div
        role="tabpanel"
        id="access-panel"
        aria-labelledby="access-tab"
        hidden={tab !== 'access'}
        className="min-w-0"
      >
        <AccessPanel />
      </div>

      {canReadAudit && (
        <div
          role="tabpanel"
          id="audit-panel"
          aria-labelledby="audit-tab"
          hidden={tab !== 'audit'}
          className="min-w-0"
        >
          <AuditPanel active={tab === 'audit'} />
        </div>
      )}

      {canManageAdmins && (
        <div
          role="tabpanel"
          id="admins-panel"
          aria-labelledby="admins-tab"
          hidden={tab !== 'admins'}
          className="min-w-0"
        >
          <AdminsPanel active={tab === 'admins'} />
        </div>
      )}

      {canReadAudit && (
        <div
          role="tabpanel"
          id="admin-audit-panel"
          aria-labelledby="admin-audit-tab"
          hidden={tab !== 'admin-audit'}
          className="min-w-0"
        >
          <AdminAuditPanel active={tab === 'admin-audit'} />
        </div>
      )}
    </div>
  );
}
