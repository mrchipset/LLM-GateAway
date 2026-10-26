import { useEffect, useRef, useState } from 'react';

import type { TenantSummary } from '../api/client';
import { useTenantPage, type TenantPageQuery } from '../hooks/useTenants';
import { formatExactNumber, formatUpdatedAt } from '../lib/format';
import { Button } from './Button';
import { CheckCircleIcon, KeyIcon, RefreshIcon } from './Icons';
import { Panel, PanelHeader } from './Panel';
import { RequestErrorPanel } from './RequestErrorPanel';
import { TenantCreateForm } from './TenantCreateForm';
import { TenantEditDialog } from './TenantEditDialog';
import { EmptyTenants, TenantsPagination, TenantsSkeleton, TenantsTable } from './TenantsTable';

export const TENANT_PAGE_SIZE = 20;

interface TenantsPanelProps {
  masterKey: string | null;
}

export function TenantsPanel({ masterKey }: TenantsPanelProps) {
  if (masterKey === null) return <DisconnectedTenantsPanel />;
  return <ConnectedTenantsPanel masterKey={masterKey} />;
}

function DisconnectedTenantsPanel() {
  return (
    <Panel labelledBy="tenants-heading">
      <PanelHeader id="tenants-heading" eyebrow="Access" title="Tenants" />
      <div className="px-5 py-4">
        <div className="flex min-h-40 flex-col items-start justify-center gap-1.5 py-4">
          <KeyIcon className="size-5 text-ink-muted" />
          <p className="mt-1 text-sm font-medium text-ink">
            Connect a master key to manage tenants.
          </p>
          <p className="max-w-md text-[13px] text-ink-muted">
            The key is sent only to the management API from this browser tab.
          </p>
        </div>
      </div>
    </Panel>
  );
}

function ConnectedTenantsPanel({ masterKey }: { masterKey: string }) {
  const [offset, setOffset] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingTenant, setEditingTenant] = useState<TenantSummary | null>(null);
  const returnFocusRef = useRef<HTMLButtonElement | null>(null);
  const pageQuery = useTenantPage(masterKey, { limit: TENANT_PAGE_SIZE, offset });

  useEffect(() => {
    if (editingTenant !== null || returnFocusRef.current === null) return;
    const trigger = returnFocusRef.current;
    returnFocusRef.current = null;
    trigger.focus();
  }, [editingTenant]);

  const count =
    pageQuery.status === 'success'
      ? `${formatExactNumber(pageQuery.data.total)} ${
          pageQuery.data.total === 1 ? 'tenant' : 'tenants'
        }`
      : null;

  const handleEdit = (tenant: TenantSummary, trigger: HTMLButtonElement) => {
    setNotice(null);
    returnFocusRef.current = trigger;
    setEditingTenant(tenant);
  };

  const handleCreated = () => {
    setOffset(0);
    setNotice('Tenant created.');
  };

  const handleSaved = (message: string) => {
    setNotice(message);
    setEditingTenant(null);
  };

  return (
    <Panel labelledBy="tenants-heading">
      <PanelHeader id="tenants-heading" eyebrow="Access" title="Tenants">
        <div className="flex items-center gap-2">
          {count !== null && (
            <span className="rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-ink">
              {count}
            </span>
          )}
          <Button
            variant="ghost"
            onClick={() => void pageQuery.refetch()}
            disabled={pageQuery.isFetching}
            aria-label="Refresh tenants"
          >
            <RefreshIcon
              className={`size-3.5 ${pageQuery.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`}
            />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>
      </PanelHeader>

      <div className="px-5 py-4" aria-busy={pageQuery.isFetching}>
        {notice !== null && (
          <p
            role="status"
            className="mb-3 flex items-center gap-1.5 rounded border border-ok/25 bg-ok-soft px-2.5 py-1.5 text-[12px] text-ok"
          >
            <CheckCircleIcon className="size-3.5" />
            {notice}
          </p>
        )}

        <TenantCreateForm
          masterKey={masterKey}
          onStart={() => setNotice(null)}
          onCreated={handleCreated}
        />

        <div className="mt-5">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
              Tenant directory
            </h3>
            {pageQuery.status === 'success' && pageQuery.dataUpdatedAt > 0 && (
              <time
                dateTime={new Date(pageQuery.dataUpdatedAt).toISOString()}
                className="font-mono text-[10.5px] tabular-nums text-ink-muted"
              >
                Updated {formatUpdatedAt(pageQuery.dataUpdatedAt)}
              </time>
            )}
          </div>

          <TenantDirectory
            query={pageQuery}
            onEdit={handleEdit}
            onPrevious={() =>
              setOffset(Math.max(0, (pageQuery.data?.offset ?? offset) - TENANT_PAGE_SIZE))
            }
            onNext={() => setOffset((pageQuery.data?.offset ?? offset) + TENANT_PAGE_SIZE)}
          />
        </div>
      </div>

      {editingTenant !== null && (
        <TenantEditDialog
          masterKey={masterKey}
          tenant={editingTenant}
          onClose={() => setEditingTenant(null)}
          onSaved={handleSaved}
        />
      )}
    </Panel>
  );
}

interface TenantDirectoryProps {
  query: TenantPageQuery;
  onEdit: (tenant: TenantSummary, trigger: HTMLButtonElement) => void;
  onPrevious: () => void;
  onNext: () => void;
}

function TenantDirectory({ query, onEdit, onPrevious, onNext }: TenantDirectoryProps) {
  if (query.isPending) return <TenantsSkeleton />;
  if (query.isError) {
    return (
      <RequestErrorPanel
        error={query.error}
        title="Could not load tenants"
        retryLabel="Retry loading tenants"
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (query.data.items.length === 0) return <EmptyTenants />;

  return (
    <>
      <TenantsTable tenants={query.data.items} onEdit={onEdit} />
      <TenantsPagination
        total={query.data.total}
        offset={query.data.offset}
        count={query.data.items.length}
        isFetching={query.isFetching}
        onPrevious={onPrevious}
        onNext={onNext}
      />
    </>
  );
}
