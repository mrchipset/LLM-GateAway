import { useAuditRequest } from '../hooks/useAudit';
import { CHANGE_TYPE_META, STATUS_META, isContentTooLarge, shortIdentifier } from '../lib/audit';
import { formatCreatedAt } from '../lib/format';
import { AuditContentSections } from './AuditContentBlocks';
import { AuditDiffView } from './AuditDiffView';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { RequestErrorPanel } from './RequestErrorPanel';

interface AuditRequestDetailProps {
  masterKey: string;
  requestId: string;
  onClose: () => void;
}

function TruncatedNote() {
  return (
    <p
      role="note"
      className="rounded border border-warn/30 bg-warn-soft px-2.5 py-1.5 text-[11.5px] text-warn"
    >
      Capture truncated this request at write time. Stored messages, parameters, or response may be
      incomplete.
    </p>
  );
}

export function AuditRequestDetail({ masterKey, requestId, onClose }: AuditRequestDetailProps) {
  const query = useAuditRequest(masterKey, requestId);

  return (
    <div className="mt-2.5 rounded-md border border-accent/30 bg-accent/5 p-2.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-accent">
            Request detail
          </p>
          <p className="mt-0.5 break-all font-mono text-[11px] text-ink" title={requestId}>
            {requestId}
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          aria-label="Close request detail"
          className="shrink-0 px-1.5 py-0.5"
        >
          <CloseIcon className="size-3.5" />
        </Button>
      </div>

      {query.isPending ? (
        <div className="mt-2">
          <span className="sr-only">Loading request…</span>
          <div aria-hidden="true" className="space-y-1.5">
            <span className="block h-3 w-2/3 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
            <span className="block h-20 w-full animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
          </div>
        </div>
      ) : query.isError ? (
        <div className="mt-2">
          {isContentTooLarge(query.error) ? (
            <div className="space-y-2">
              <RequestErrorPanel
                error={query.error}
                title="Request content is too large"
                retryLabel="Retry loading request content"
                onRetry={() => void query.refetch()}
              />
              <p className="text-[11.5px] text-ink-muted">
                This single request is over the configured content budget. The timeline still shows
                its metadata and diff; this endpoint cannot return the full body.
              </p>
            </div>
          ) : (
            <RequestErrorPanel
              error={query.error}
              title="Could not load request detail"
              retryLabel="Retry loading request detail"
              onRetry={() => void query.refetch()}
            />
          )}
        </div>
      ) : (
        <div className="mt-2 space-y-2">
          {query.data.request.truncated && <TruncatedNote />}

          <dl className="grid gap-x-4 gap-y-1 text-[11.5px] sm:grid-cols-[7rem_minmax(0,1fr)]">
            <dt className="text-ink-muted">Session</dt>
            <dd className="break-all font-mono text-[11px]" title={query.data.request.session_id}>
              {shortIdentifier(query.data.request.session_id)}
            </dd>
            <dt className="text-ink-muted">Turn</dt>
            <dd className="font-mono tabular-nums text-[11px]">{query.data.request.turn_index}</dd>
            <dt className="text-ink-muted">Created (UTC)</dt>
            <dd className="font-mono tabular-nums text-[11px]">
              <time dateTime={query.data.request.created_at}>
                {formatCreatedAt(query.data.request.created_at)}
              </time>
            </dd>
            <dt className="text-ink-muted">Change / status</dt>
            <dd className="flex flex-wrap gap-1.5">
              <span
                className={`inline-flex rounded border px-1.5 py-0.5 font-mono text-[10.5px] font-medium ${CHANGE_TYPE_META[query.data.request.change_type].className}`}
              >
                {CHANGE_TYPE_META[query.data.request.change_type].label}
              </span>
              <span
                className={`inline-flex rounded border px-1.5 py-0.5 font-mono text-[10.5px] font-medium ${STATUS_META[query.data.request.status].className}`}
              >
                {STATUS_META[query.data.request.status].label}
              </span>
            </dd>
          </dl>

          <AuditContentSections
            messages={query.data.request.request_messages}
            params={query.data.request.request_params}
            responseContent={query.data.request.response_content}
            responseToolCalls={query.data.request.response_tool_calls}
          />

          <section aria-label="Request diff">
            <h5 className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted">
              Diff
            </h5>
            <AuditDiffView diff={query.data.diff} includeContent />
          </section>
        </div>
      )}
    </div>
  );
}
