import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState } from 'react';

import type { ApiKeySummary, CreatedApiKey } from '../api/client';
import { discardCreateKeyMutation, useCreateKey } from '../hooks/useKeyMutations';
import { useKeyPage } from '../hooks/useKeys';
import { useTenants } from '../hooks/useTenants';
import { formatExactNumber, formatUpdatedAt } from '../lib/format';
import { Button } from './Button';
import { CheckCircleIcon, KeyIcon, RefreshIcon } from './Icons';
import { KeyCreateDialog } from './KeyCreateDialog';
import { KeyRevokeDialog } from './KeyRevokeDialog';
import { KeySecretDialog } from './KeySecretDialog';
import { EmptyKeys, KeysPagination, KeysSkeleton, KeysTable } from './KeysTable';
import { Panel, PanelHeader } from './Panel';
import { RequestErrorPanel } from './RequestErrorPanel';

export const KEY_PAGE_SIZE = 20;

interface KeysPanelProps {
  masterKey: string | null;
}

export function KeysPanel({ masterKey }: KeysPanelProps) {
  if (masterKey === null) return <DisconnectedKeysPanel />;
  return <ConnectedKeysPanel masterKey={masterKey} />;
}

function DisconnectedKeysPanel() {
  return (
    <Panel labelledBy="keys-heading">
      <PanelHeader id="keys-heading" eyebrow="Access" title="API keys" />
      <div className="px-5 py-4">
        <div className="flex min-h-40 flex-col items-start justify-center gap-1.5 py-4">
          <KeyIcon className="size-5 text-ink-muted" />
          <p className="mt-1 text-sm font-medium text-ink">
            Connect a master key to manage API keys.
          </p>
          <p className="max-w-md text-[13px] text-ink-muted">
            The key is sent only to the management API from this browser tab.
          </p>
        </div>
      </div>
    </Panel>
  );
}

function ConnectedKeysPanel({ masterKey }: { masterKey: string }) {
  const [tenantFilter, setTenantFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [secret, setSecret] = useState<CreatedApiKey | null>(null);
  const [revokingKey, setRevokingKey] = useState<ApiKeySummary | null>(null);
  const filterId = useId();
  const createButtonRef = useRef<HTMLButtonElement>(null);
  const revokeTriggerRef = useRef<HTMLElement | null>(null);
  const queryClient = useQueryClient();

  const tenantsQuery = useTenants(masterKey);
  const tenants = tenantsQuery.data?.items ?? [];
  const canCreate = tenantsQuery.status === 'success' && tenants.length > 0;
  const tenantNames = new Map(tenants.map((tenant) => [tenant.id, tenant.name]));

  const keyPage = useKeyPage(masterKey, {
    tenantId: tenantFilter === '' ? null : tenantFilter,
    limit: KEY_PAGE_SIZE,
    offset,
  });
  const createMutation = useCreateKey(masterKey);

  useEffect(() => {
    return () => {
      discardCreateKeyMutation(queryClient);
    };
  }, [queryClient]);

  const count =
    keyPage.status === 'success'
      ? `${formatExactNumber(keyPage.data.total)} ${keyPage.data.total === 1 ? 'key' : 'keys'}`
      : null;

  const openCreate = () => {
    setNotice(null);
    setCreateOpen(true);
  };

  const closeCreate = () => {
    setCreateOpen(false);
    createMutation.reset();
    discardCreateKeyMutation(queryClient);
  };

  const handleFilterChange = (value: string) => {
    setTenantFilter(value);
    setOffset(0);
    setNotice(null);
  };

  const handleCreated = (created: CreatedApiKey) => {
    setSecret(created);
    setCreateOpen(false);
    createMutation.reset();
    discardCreateKeyMutation(queryClient);
  };

  const closeSecret = () => {
    setSecret(null);
    createMutation.reset();
    discardCreateKeyMutation(queryClient);
  };

  const handleRevoke = (apiKey: ApiKeySummary, trigger: HTMLButtonElement) => {
    setNotice(null);
    revokeTriggerRef.current = trigger;
    setRevokingKey(apiKey);
  };

  return (
    <Panel labelledBy="keys-heading">
      <PanelHeader id="keys-heading" eyebrow="Access" title="API keys">
        <div className="flex items-center gap-2">
          {count !== null && (
            <span className="rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-ink">
              {count}
            </span>
          )}
          <Button
            variant="ghost"
            onClick={() => void keyPage.refetch()}
            disabled={keyPage.isFetching}
            aria-label="Refresh API keys"
          >
            <RefreshIcon
              className={`size-3.5 ${keyPage.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`}
            />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>
      </PanelHeader>

      <div className="px-5 py-4" aria-busy={keyPage.isFetching}>
        {notice !== null && (
          <p
            role="status"
            className="mb-3 flex items-center gap-1.5 rounded border border-ok/25 bg-ok-soft px-2.5 py-1.5 text-[12px] text-ok"
          >
            <CheckCircleIcon className="size-3.5" />
            {notice}
          </p>
        )}

        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
          <div className="w-full max-w-xs">
            <label
              htmlFor={filterId}
              className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
            >
              Tenant filter
            </label>
            <select
              id={filterId}
              value={tenantFilter}
              onChange={(event) => handleFilterChange(event.target.value)}
              disabled={tenantsQuery.isPending}
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[12.5px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            >
              <option value="">All tenants</option>
              {tenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {tenantsQuery.status === 'success' && tenants.length === 0 && (
              <p className="text-[11.5px] text-warn">Create a tenant first.</p>
            )}
            <Button ref={createButtonRef} onClick={openCreate} disabled={!canCreate}>
              Create API key
            </Button>
          </div>
        </div>

        <div className="mt-5">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
              Key directory
            </h3>
            {keyPage.status === 'success' && keyPage.dataUpdatedAt > 0 && (
              <time
                dateTime={new Date(keyPage.dataUpdatedAt).toISOString()}
                className="font-mono text-[10.5px] tabular-nums text-ink-muted"
              >
                Updated {formatUpdatedAt(keyPage.dataUpdatedAt)}
              </time>
            )}
          </div>

          <KeyDirectory
            query={keyPage}
            tenants={tenantNames}
            canCreate={canCreate}
            onCreate={openCreate}
            onRevoke={handleRevoke}
            onPrevious={() =>
              setOffset(Math.max(0, (keyPage.data?.offset ?? offset) - KEY_PAGE_SIZE))
            }
            onNext={() => setOffset((keyPage.data?.offset ?? offset) + KEY_PAGE_SIZE)}
          />
        </div>
      </div>

      {createOpen && (
        <KeyCreateDialog
          tenants={tenants}
          initialTenantId={tenantFilter === '' ? null : tenantFilter}
          createMutation={createMutation}
          returnFocusRef={createButtonRef}
          onClose={closeCreate}
          onCreated={handleCreated}
        />
      )}

      {secret !== null && (
        <KeySecretDialog created={secret} returnFocusRef={createButtonRef} onClose={closeSecret} />
      )}

      {revokingKey !== null && (
        <KeyRevokeDialog
          masterKey={masterKey}
          apiKey={revokingKey}
          returnFocusRef={revokeTriggerRef}
          onClose={() => setRevokingKey(null)}
          onRevoked={() => {
            setRevokingKey(null);
            setNotice('API key revoked.');
          }}
        />
      )}
    </Panel>
  );
}

interface KeyDirectoryProps {
  query: ReturnType<typeof useKeyPage>;
  tenants: ReadonlyMap<string, string>;
  canCreate: boolean;
  onCreate: () => void;
  onRevoke: (apiKey: ApiKeySummary, trigger: HTMLButtonElement) => void;
  onPrevious: () => void;
  onNext: () => void;
}

function KeyDirectory({
  query,
  tenants,
  canCreate,
  onCreate,
  onRevoke,
  onPrevious,
  onNext,
}: KeyDirectoryProps) {
  if (query.isPending) return <KeysSkeleton />;
  if (query.isError) {
    return (
      <RequestErrorPanel
        error={query.error}
        title="Could not load API keys"
        retryLabel="Retry loading API keys"
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (query.data.items.length === 0) {
    return <EmptyKeys createDisabled={!canCreate} onCreate={onCreate} />;
  }

  const now = query.dataUpdatedAt;

  return (
    <>
      <KeysTable keys={query.data.items} tenantNames={tenants} now={now} onRevoke={onRevoke} />
      <KeysPagination
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
