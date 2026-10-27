import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from 'react';

import { ApiRequestError, type AuditSessionSummary } from '../api/client';
import { useAuditKeyOptions, useAuditSessions } from '../hooks/useAudit';
import { useModels } from '../hooks/useModels';
import { TENANT_SELECTOR_LIMIT, useTenants } from '../hooks/useTenants';
import {
  AUDIT_PAGE_SIZE,
  AUDIT_RANGE_PRESETS,
  DEFAULT_AUDIT_RANGE_DAYS,
  auditRangeSinceIso,
  type AuditRangeDays,
} from '../lib/audit';
import { formatExactNumber, formatUpdatedAt } from '../lib/format';
import { AuditIcon, RefreshIcon } from './Icons';
import { Panel, PanelHeader } from './Panel';
import { RequestErrorPanel } from './RequestErrorPanel';
import { AuditSessionDetail } from './AuditSessionDetail';
import {
  AuditPagination,
  AuditSessionsSkeleton,
  AuditSessionsTable,
  EmptyAuditSessions,
} from './AuditSessionsTable';
import { Button } from './Button';

interface AuditPanelProps {
  masterKey: string | null;
}

export function AuditPanel({ masterKey }: AuditPanelProps) {
  if (masterKey === null) return <DisconnectedAuditPanel />;
  return <ConnectedAuditPanel masterKey={masterKey} />;
}

function DisconnectedAuditPanel() {
  return (
    <Panel labelledBy="audit-heading">
      <PanelHeader id="audit-heading" eyebrow="History" title="Audit" />
      <div className="px-5 py-4">
        <div className="flex min-h-40 flex-col items-start justify-center gap-1.5 py-4">
          <AuditIcon className="size-5 text-ink-muted" />
          <p className="mt-1 text-sm font-medium text-ink">
            Connect a master key to view the audit log.
          </p>
          <p className="max-w-md text-[13px] text-ink-muted">
            The key is sent only to the management API from this browser tab. Audit history is
            read-only here.
          </p>
        </div>
      </div>
    </Panel>
  );
}

function InlineLoadError({
  message,
  error,
  onRetry,
}: {
  message: string;
  error: Error;
  onRetry: () => void;
}) {
  const requestError = error instanceof ApiRequestError ? error : null;
  return (
    <p
      role="alert"
      className="mt-2 rounded border border-danger/25 bg-danger-soft/60 px-2.5 py-1.5 text-[11.5px] text-danger"
    >
      {message}
      {requestError?.requestId !== null && requestError?.requestId !== undefined && (
        <span className="ml-1 font-mono">Request ID: {requestError.requestId}.</span>
      )}{' '}
      <button
        type="button"
        onClick={onRetry}
        className="font-medium underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        Retry
      </button>
    </p>
  );
}

function ConnectedAuditPanel({ masterKey }: { masterKey: string }) {
  const [tenantId, setTenantId] = useState('');
  const [apiKeyId, setApiKeyId] = useState('');
  const [modelId, setModelId] = useState('');
  const [draftQuery, setDraftQuery] = useState('');
  const [query, setQuery] = useState('');
  const [rangeDays, setRangeDays] = useState<AuditRangeDays>(DEFAULT_AUDIT_RANGE_DAYS);
  const [anchor, setAnchor] = useState(() => new Date());
  const [offset, setOffset] = useState(0);
  const [selectedSession, setSelectedSession] = useState<AuditSessionSummary | null>(null);

  const sessionDirectoryHeadingRef = useRef<HTMLHeadingElement>(null);
  const lastOpenedSessionIdRef = useRef<string | null>(null);
  const restoreSessionFocusRef = useRef(false);

  const tenantSelectId = useId();
  const keySelectId = useId();
  const modelSelectId = useId();
  const rangeLabelId = useId();
  const searchId = useId();
  const noteId = useId();

  const since = useMemo(() => auditRangeSinceIso(rangeDays, anchor), [rangeDays, anchor]);
  const sessionsQuery = useAuditSessions(masterKey, {
    tenantId: tenantId === '' ? null : tenantId,
    apiKeyId: apiKeyId === '' ? null : apiKeyId,
    modelId: modelId === '' ? null : modelId,
    q: query === '' ? null : query,
    since,
    limit: AUDIT_PAGE_SIZE,
    offset,
  });
  const tenantsQuery = useTenants(masterKey);
  const keysQuery = useAuditKeyOptions(masterKey, tenantId === '' ? null : tenantId);
  const modelsQuery = useModels(masterKey);

  const tenants = tenantsQuery.data?.items ?? [];
  const tenantNames = new Map(tenants.map((tenant) => [tenant.id, tenant.name]));
  const selectedTenant = tenants.find((tenant) => tenant.id === tenantId) ?? null;
  const auditOff = selectedTenant !== null && !selectedTenant.audit_enabled;
  const keys = keysQuery.data?.items ?? [];
  const models = modelsQuery.data?.items ?? [];

  const count =
    sessionsQuery.status === 'success'
      ? `${formatExactNumber(sessionsQuery.data.total)} ${
          sessionsQuery.data.total === 1 ? 'session' : 'sessions'
        }`
      : null;

  const refreshFilters = () => {
    void sessionsQuery.refetch();
    void tenantsQuery.refetch();
    if (tenantId !== '') void keysQuery.refetch();
    void modelsQuery.refetch();
  };

  const handleRefresh = () => {
    const nextAnchor = new Date();
    setAnchor(nextAnchor);
    if (auditRangeSinceIso(rangeDays, nextAnchor) === since) refreshFilters();
  };

  const handleTenantChange = (value: string) => {
    setTenantId(value);
    setApiKeyId('');
    setOffset(0);
  };

  const handleKeyChange = (value: string) => {
    setApiKeyId(value);
    setOffset(0);
  };

  const handleModelChange = (value: string) => {
    setModelId(value);
    setOffset(0);
  };

  const handleRangeChange = (days: AuditRangeDays) => {
    setRangeDays(days);
    setAnchor(new Date());
    setOffset(0);
  };

  const handleSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setQuery(draftQuery.trim());
    setOffset(0);
  };

  const handleClearSearch = () => {
    setDraftQuery('');
    setQuery('');
    setOffset(0);
  };

  const handleOpenSession = (session: AuditSessionSummary) => {
    lastOpenedSessionIdRef.current = session.id;
    setSelectedSession(session);
  };

  const handleBackToSessions = () => {
    restoreSessionFocusRef.current = true;
    setSelectedSession(null);
  };

  useEffect(() => {
    if (selectedSession !== null || !restoreSessionFocusRef.current) return;
    restoreSessionFocusRef.current = false;

    const sessionId = lastOpenedSessionIdRef.current;
    const candidates =
      sessionId === null
        ? []
        : Array.from(
            document.querySelectorAll<HTMLButtonElement>('[data-audit-session-open]'),
          ).filter((button) => button.dataset.auditSessionOpen === sessionId);
    const target = candidates.find((button) => button.offsetParent !== null) ?? candidates[0];

    if (target !== undefined) {
      target.focus();
      return;
    }
    sessionDirectoryHeadingRef.current?.focus();
  }, [selectedSession]);

  if (selectedSession !== null) {
    return (
      <Panel labelledBy="audit-heading">
        <PanelHeader id="audit-heading" eyebrow="History" title="Audit">
          <span className="rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10.5px] text-ink-muted">
            Session
          </span>
        </PanelHeader>
        <div className="px-5 py-4">
          <AuditSessionDetail
            masterKey={masterKey}
            session={selectedSession}
            tenantName={tenantNames.get(selectedSession.tenant_id) ?? null}
            onBack={handleBackToSessions}
          />
        </div>
      </Panel>
    );
  }

  return (
    <Panel labelledBy="audit-heading">
      <PanelHeader id="audit-heading" eyebrow="History" title="Audit">
        <div className="flex items-center gap-2">
          {count !== null && (
            <span className="rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-ink">
              {count}
            </span>
          )}
          <Button
            variant="ghost"
            onClick={handleRefresh}
            disabled={sessionsQuery.isFetching}
            aria-label="Refresh audit sessions"
          >
            <RefreshIcon
              className={`size-3.5 ${sessionsQuery.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`}
            />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>
      </PanelHeader>

      <div className="px-5 py-4" aria-busy={sessionsQuery.isFetching}>
        <div className="border-b border-line pb-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="min-w-0">
              <label
                htmlFor={tenantSelectId}
                className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
              >
                Audit tenant
              </label>
              <select
                id={tenantSelectId}
                value={tenantId}
                onChange={(event) => handleTenantChange(event.target.value)}
                disabled={tenantsQuery.isPending}
                aria-describedby={auditOff ? noteId : undefined}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[12.5px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              >
                <option value="">All tenants</option>
                {tenants.map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>
                    {tenant.name}
                  </option>
                ))}
              </select>
              {tenantsQuery.status === 'success' &&
                tenantsQuery.data.total > TENANT_SELECTOR_LIMIT && (
                  <p className="mt-1 text-[10.5px] text-ink-muted">
                    Showing the first {formatExactNumber(TENANT_SELECTOR_LIMIT)} of{' '}
                    {formatExactNumber(tenantsQuery.data.total)} tenants.
                  </p>
                )}
            </div>

            <div className="min-w-0">
              <label
                htmlFor={keySelectId}
                className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
              >
                API key
              </label>
              <select
                id={keySelectId}
                value={apiKeyId}
                onChange={(event) => handleKeyChange(event.target.value)}
                disabled={tenantId === '' || keysQuery.isPending}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[12.5px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              >
                {tenantId === '' ? (
                  <option value="">Select a tenant first</option>
                ) : (
                  <>
                    <option value="">All keys</option>
                    {keys.map((key) => (
                      <option key={key.id} value={key.id}>
                        {key.name} · {key.key_prefix}
                      </option>
                    ))}
                  </>
                )}
              </select>
            </div>

            <div className="min-w-0">
              <label
                htmlFor={modelSelectId}
                className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
              >
                Model
              </label>
              <select
                id={modelSelectId}
                value={modelId}
                onChange={(event) => handleModelChange(event.target.value)}
                disabled={modelsQuery.isPending}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[12.5px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              >
                <option value="">All models</option>
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.id}
                  </option>
                ))}
              </select>
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
                {AUDIT_RANGE_PRESETS.map((preset) => {
                  const active = rangeDays === preset.days;
                  return (
                    <button
                      key={preset.days}
                      type="button"
                      aria-pressed={active}
                      onClick={() => handleRangeChange(preset.days)}
                      className={`rounded px-2.5 py-1 font-mono text-[11px] tabular-nums transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                        active
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

          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <form onSubmit={handleSearch} className="flex w-full max-w-xl items-end gap-2">
              <div className="min-w-0 flex-1">
                <label
                  htmlFor={searchId}
                  className="block font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
                >
                  Search
                </label>
                <input
                  id={searchId}
                  type="search"
                  value={draftQuery}
                  maxLength={200}
                  onChange={(event) => setDraftQuery(event.target.value)}
                  placeholder="Title, session ID, or request ID"
                  className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15"
                />
              </div>
              <Button type="submit" variant="secondary" className="shrink-0">
                Search
              </Button>
              {(draftQuery !== '' || query !== '') && (
                <Button variant="ghost" onClick={handleClearSearch} className="shrink-0">
                  Clear
                </Button>
              )}
            </form>

            {sessionsQuery.status === 'success' && sessionsQuery.dataUpdatedAt > 0 && (
              <time
                dateTime={new Date(sessionsQuery.dataUpdatedAt).toISOString()}
                className="shrink-0 font-mono text-[10.5px] tabular-nums text-ink-muted"
              >
                Updated {formatUpdatedAt(sessionsQuery.dataUpdatedAt)}
              </time>
            )}
          </div>

          {auditOff && selectedTenant !== null && (
            <p
              id={noteId}
              role="status"
              className="mt-3 rounded border border-warn/30 bg-warn-soft px-2.5 py-1.5 text-[11.5px] text-warn"
            >
              Audit collection is off for {selectedTenant.name}. New requests are not captured.
              Enable it in Access → Tenants.
            </p>
          )}

          {tenantsQuery.isError && (
            <InlineLoadError
              message="Could not load tenants for the filter."
              error={tenantsQuery.error}
              onRetry={() => void tenantsQuery.refetch()}
            />
          )}
          {keysQuery.isError && tenantId !== '' && (
            <InlineLoadError
              message="Could not load API keys for this tenant."
              error={keysQuery.error}
              onRetry={() => void keysQuery.refetch()}
            />
          )}
          {modelsQuery.isError && (
            <InlineLoadError
              message="Could not load models for the filter."
              error={modelsQuery.error}
              onRetry={() => void modelsQuery.refetch()}
            />
          )}
        </div>

        <p className="mt-3 rounded border border-line bg-surface-sunken/40 px-2.5 py-1.5 text-[11.5px] text-ink-muted">
          Read-only history. Diffs always include bounded preview excerpts of up to 160 characters.
          Full session content loads only when you turn on Show full content; single requests can be
          opened on demand. Nothing is stored in the browser.
        </p>

        <div className="mt-4">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h3
              ref={sessionDirectoryHeadingRef}
              tabIndex={-1}
              className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted focus:outline-none"
            >
              Session directory
            </h3>
            {sessionsQuery.status === 'success' && sessionsQuery.data.total > 0 && (
              <p className="font-mono text-[10.5px] tabular-nums text-ink-muted">
                Newest activity first
              </p>
            )}
          </div>

          {sessionsQuery.isPending ? (
            <AuditSessionsSkeleton />
          ) : sessionsQuery.isError ? (
            <RequestErrorPanel
              error={sessionsQuery.error}
              title="Could not load audit sessions"
              retryLabel="Retry loading audit sessions"
              onRetry={() => void sessionsQuery.refetch()}
            />
          ) : sessionsQuery.data.items.length === 0 ? (
            <EmptyAuditSessions />
          ) : (
            <>
              <AuditSessionsTable
                sessions={sessionsQuery.data.items}
                tenantNames={tenantNames}
                onOpen={handleOpenSession}
              />
              <AuditPagination
                total={sessionsQuery.data.total}
                offset={sessionsQuery.data.offset}
                count={sessionsQuery.data.items.length}
                isFetching={sessionsQuery.isFetching}
                onPrevious={() =>
                  setOffset(Math.max(0, (sessionsQuery.data?.offset ?? offset) - AUDIT_PAGE_SIZE))
                }
                onNext={() => setOffset((sessionsQuery.data?.offset ?? offset) + AUDIT_PAGE_SIZE)}
              />
            </>
          )}
        </div>
      </div>
    </Panel>
  );
}
