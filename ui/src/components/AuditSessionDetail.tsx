import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

import type { AuditSessionSummary, AuditStatus } from '../api/client';
import { useAuditSession } from '../hooks/useAudit';
import { auditSessionTitle, isContentTooLarge, shortIdentifier } from '../lib/audit';
import { formatCreatedAt, formatExactNumber } from '../lib/format';
import { Button } from './Button';
import { BackIcon } from './Icons';
import { RequestErrorPanel } from './RequestErrorPanel';
import { AuditTurnCard } from './AuditTurnCard';

const DOT_CLASSES: Record<AuditStatus, string> = {
  completed: 'border-ok bg-ok',
  upstream_error: 'border-danger bg-danger',
  client_error: 'border-warn bg-warn',
  client_disconnected: 'border-warn bg-warn',
  error: 'border-danger bg-danger',
};

interface AuditSessionDetailProps {
  masterKey: string;
  session: AuditSessionSummary;
  tenantName: string | null;
  onBack: () => void;
}

function DetailSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading session detail…</span>
      <div aria-hidden="true" className="space-y-2">
        {[0, 1, 2].map((row) => (
          <div key={row} className="rounded border border-line/70 px-3 py-3">
            <span className="block h-3 w-1/3 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
            <span className="mt-2 block h-3 w-4/5 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
            <span className="mt-2 block h-3 w-2/3 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
          </div>
        ))}
      </div>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="break-words text-ink">{children}</dd>
    </div>
  );
}

export function AuditSessionDetail({
  masterKey,
  session,
  tenantName,
  onBack,
}: AuditSessionDetailProps) {
  const [includeContent, setIncludeContent] = useState(false);
  const query = useAuditSession(masterKey, session.id, includeContent);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const privacyId = useId();

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const title = auditSessionTitle(session.title_preview);
  const detail = query.data?.session ?? session;
  const loadingContent = query.isFetching && !query.isPending;
  const contentTooLarge = query.isError && isContentTooLarge(query.error);

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Button
            variant="ghost"
            onClick={onBack}
            aria-label="Back to all sessions"
            className="-ml-1.5 px-2 py-1 text-[12px]"
          >
            <BackIcon className="size-3.5" />
            All sessions
          </Button>
          <h3
            ref={headingRef}
            tabIndex={-1}
            className="mt-1 text-[16px] font-semibold leading-snug tracking-[-0.01em] text-ink focus:outline-none"
          >
            {title}
          </h3>
          <p className="mt-1 break-all font-mono text-[10.5px] text-ink-muted">
            <span className="select-all" title={detail.id}>
              {shortIdentifier(detail.id)}
            </span>
            {detail.external_session_id !== null && (
              <span className="ml-2">external: {detail.external_session_id}</span>
            )}
          </p>
        </div>
        <p className="rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10.5px] text-ink-muted">
          Read-only
        </p>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-line bg-surface-sunken/40 px-3 py-2 text-[11.5px] sm:grid-cols-3">
        <Fact label="Tenant">{tenantName ?? shortIdentifier(detail.tenant_id)}</Fact>
        <Fact label="Key prefix">
          <span className="font-mono text-[11px]">{detail.api_key_prefix}</span>
        </Fact>
        <Fact label="Model">
          <span className="font-mono text-[11px]">{detail.model_id}</span>
          <span className="text-ink-muted"> · {detail.provider}</span>
        </Fact>
        <Fact label="Requests">{formatExactNumber(detail.request_count)}</Fact>
        <Fact label="Tokens">{formatExactNumber(detail.total_tokens)}</Fact>
        <Fact label="Last seen (UTC)">
          <time dateTime={detail.last_seen_at} className="font-mono text-[11px] tabular-nums">
            {formatCreatedAt(detail.last_seen_at)}
          </time>
        </Fact>
      </dl>

      <div className="mt-3 rounded-md border border-line bg-surface-sunken/40 px-3 py-2">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[12px] font-medium text-ink">Preview excerpts are always included</p>
            <p id={privacyId} className="mt-0.5 max-w-2xl text-[11.5px] leading-5 text-ink-muted">
              {includeContent
                ? 'Full session content is fetched on demand for this view and is never stored in the browser. Diff previews stay bounded excerpts of up to 160 characters.'
                : 'Diffs include bounded preview excerpts of up to 160 characters. Full session content stays hidden until you turn on Show full content; opening a single request fetches just that request on demand. Nothing is stored in the browser.'}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-start gap-1">
            <button
              type="button"
              role="switch"
              aria-checked={includeContent}
              aria-describedby={privacyId}
              onClick={() => setIncludeContent((current) => !current)}
              className="inline-flex items-center gap-2 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <span
                aria-hidden="true"
                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                  includeContent ? 'bg-accent' : 'bg-line-strong'
                }`}
              >
                <span
                  className={`absolute top-0.5 size-4 rounded-full bg-white shadow-sm transition-transform ${
                    includeContent ? 'translate-x-[1.125rem]' : 'translate-x-0.5'
                  }`}
                />
              </span>
              <span className="text-[12px] font-medium text-ink">Show full content</span>
            </button>
            {loadingContent && (
              <span role="status" className="text-[10.5px] text-ink-muted">
                Loading content…
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4" aria-busy={query.isFetching}>
        {query.isError ? (
          contentTooLarge ? (
            <div className="space-y-2">
              <RequestErrorPanel
                error={query.error}
                title={
                  includeContent ? 'Session content is too large' : 'Session metadata is too large'
                }
                retryLabel="Retry loading session detail"
                onRetry={() => void query.refetch()}
              />
              <div className="rounded-md border border-line bg-surface-sunken/40 px-3 py-2 text-[12px] text-ink-muted">
                <p>
                  {includeContent
                    ? 'This response is over the configured audit content budget, so nothing is silently cut off. Hide full content to load the timeline and diffs, then use Open request on a turn to fetch one request at a time.'
                    : 'This session exceeds the response size limit and cannot be partially rendered here. Use the request endpoint with a request id, or raise GATEWAY_AUDIT_MAX_CONTENT_BYTES and restart the gateway.'}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {includeContent && (
                    <Button variant="secondary" onClick={() => setIncludeContent(false)}>
                      Hide full content
                    </Button>
                  )}
                  <Button variant="ghost" onClick={onBack}>
                    Back to sessions
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <RequestErrorPanel
                error={query.error}
                title="Could not load session detail"
                retryLabel="Retry loading session detail"
                onRetry={() => void query.refetch()}
              />
              <Button variant="ghost" onClick={onBack}>
                Back to sessions
              </Button>
            </div>
          )
        ) : query.isPending ? (
          <DetailSkeleton />
        ) : query.data.turns.length === 0 ? (
          <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
            <h4 className="text-sm font-semibold text-ink">No turns recorded</h4>
            <p className="mt-1 text-[13px] text-ink-muted">
              This session has metadata but no captured turns.
            </p>
          </div>
        ) : (
          <>
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h4 className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
                Turn timeline
              </h4>
              <p className="font-mono text-[10.5px] tabular-nums text-ink-muted">
                {formatExactNumber(query.data.turns.length)}{' '}
                {query.data.turns.length === 1 ? 'turn' : 'turns'}
              </p>
            </div>
            <ol
              aria-label="Session turns"
              className="relative ml-1 space-y-3 border-l border-line pl-4"
            >
              {query.data.turns.map((turn) => (
                <li key={turn.request_id} className="relative">
                  <span
                    aria-hidden="true"
                    className={`absolute -left-[1.32rem] top-4 size-2 rounded-full border ${DOT_CLASSES[turn.status]}`}
                  />
                  <AuditTurnCard
                    masterKey={masterKey}
                    turn={turn}
                    includeContent={includeContent}
                    contentReady={!loadingContent}
                  />
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}
