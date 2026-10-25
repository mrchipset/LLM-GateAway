import { useMemo, useRef, useState, type KeyboardEvent } from 'react';

import type { ModelsQuery } from '../hooks/useModels';
import { useTenants } from '../hooks/useTenants';
import { useUsageByKey, useUsageSeries, useUsageSummary } from '../hooks/useUsage';
import { DEFAULT_USAGE_RANGE_DAYS, usageRangeSinceIso, type UsageRangeDays } from '../lib/usage';
import { ModelsIcon, UsageIcon } from './Icons';
import { ModelsPanel } from './ModelsPanel';
import { UsagePanel } from './UsagePanel';

const TABS = [
  { id: 'models', label: 'Models', Icon: ModelsIcon },
  { id: 'usage', label: 'Usage', Icon: UsageIcon },
] as const;

type WorkspaceTab = (typeof TABS)[number]['id'];

interface WorkspaceProps {
  masterKey: string | null;
  modelsQuery: ModelsQuery;
}

export function Workspace({ masterKey, modelsQuery }: WorkspaceProps) {
  const [tab, setTab] = useState<WorkspaceTab>('models');
  const [tenantId, setTenantId] = useState('');
  const [rangeDays, setRangeDays] = useState<UsageRangeDays>(DEFAULT_USAGE_RANGE_DAYS);
  const tabRefs = useRef<Partial<Record<WorkspaceTab, HTMLButtonElement | null>>>({});

  const since = useMemo(() => usageRangeSinceIso(rangeDays), [rangeDays]);
  const usageWindow = useMemo(
    () => ({ tenantId: tenantId === '' ? null : tenantId, since }),
    [tenantId, since],
  );

  const tenantsQuery = useTenants(masterKey);
  const summaryQuery = useUsageSummary(masterKey, usageWindow);
  const seriesQuery = useUsageSeries(masterKey, usageWindow);
  const byKeyQuery = useUsageByKey(masterKey, usageWindow);

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const currentIndex = TABS.findIndex((item) => item.id === tab);
    if (currentIndex === -1) return;

    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % TABS.length;
    if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + TABS.length) % TABS.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = TABS.length - 1;
    if (nextIndex === null) return;

    const nextTab = TABS[nextIndex];
    if (nextTab === undefined) return;

    event.preventDefault();
    setTab(nextTab.id);
    tabRefs.current[nextTab.id]?.focus();
  };

  return (
    <div>
      <div className="mb-3 flex items-center">
        <div
          role="tablist"
          aria-label="Admin sections"
          className="inline-flex rounded-md border border-line bg-surface-sunken p-0.5"
        >
          {TABS.map((item) => {
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
                className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-[12px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
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

      <div
        role="tabpanel"
        id="models-panel"
        aria-labelledby="models-tab"
        hidden={tab !== 'models'}
        className="min-w-0"
      >
        <ModelsPanel masterKey={masterKey} query={modelsQuery} />
      </div>

      <div
        role="tabpanel"
        id="usage-panel"
        aria-labelledby="usage-tab"
        hidden={tab !== 'usage'}
        className="min-w-0"
      >
        <UsagePanel
          masterKey={masterKey}
          tenantId={tenantId}
          rangeDays={rangeDays}
          onTenantChange={setTenantId}
          onRangeChange={setRangeDays}
          tenantsQuery={tenantsQuery}
          summaryQuery={summaryQuery}
          seriesQuery={seriesQuery}
          byKeyQuery={byKeyQuery}
        />
      </div>
    </div>
  );
}
