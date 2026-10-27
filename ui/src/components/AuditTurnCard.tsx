import { useState } from 'react';

import type { AuditTurn } from '../api/client';
import { CHANGE_TYPE_META, MATCH_METHOD_LABEL, STATUS_META, shortIdentifier } from '../lib/audit';
import { formatCreatedAt, formatExactNumber } from '../lib/format';
import { AuditContentSections } from './AuditContentBlocks';
import { AuditDiffView } from './AuditDiffView';
import { AuditRequestDetail } from './AuditRequestDetail';
import { Button } from './Button';

interface AuditTurnCardProps {
  masterKey: string;
  turn: AuditTurn;
  includeContent: boolean;
  contentReady?: boolean;
}

function Badge({
  children,
  className,
  title,
}: {
  children: string;
  className: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[10.5px] font-medium ${className}`}
    >
      {children}
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="font-mono tabular-nums text-ink">{value}</dd>
    </div>
  );
}

export function AuditTurnCard({
  masterKey,
  turn,
  includeContent,
  contentReady = true,
}: AuditTurnCardProps) {
  const [requestOpen, setRequestOpen] = useState(false);
  const change = CHANGE_TYPE_META[turn.change_type];
  const status = STATUS_META[turn.status];

  return (
    <article className="rounded-md border border-line bg-surface px-3 py-2.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-[11px] font-medium text-ink">Turn {turn.turn_index}</p>
          <time
            dateTime={turn.created_at}
            className="mt-0.5 block font-mono text-[10.5px] tabular-nums text-ink-muted"
          >
            {formatCreatedAt(turn.created_at)}
          </time>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge className={change.className}>{change.label}</Badge>
          <Badge className={status.className}>{status.label}</Badge>
          <Badge
            className="border-line-strong bg-surface-sunken text-ink-muted"
            title={`Match method: ${turn.match_method}`}
          >
            {`Match: ${MATCH_METHOD_LABEL[turn.match_method]}`}
          </Badge>
          <Badge className="border-line bg-surface text-ink-muted">
            {turn.is_stream ? 'Stream' : 'Buffered'}
          </Badge>
        </div>
      </div>

      <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px]">
        <Metric label="Messages" value={formatExactNumber(turn.request_message_count)} />
        <Metric
          label="Prompt"
          value={turn.prompt_tokens === null ? '—' : formatExactNumber(turn.prompt_tokens)}
        />
        <Metric
          label="Completion"
          value={turn.completion_tokens === null ? '—' : formatExactNumber(turn.completion_tokens)}
        />
        <Metric
          label="Total"
          value={turn.total_tokens === null ? '—' : formatExactNumber(turn.total_tokens)}
        />
        <Metric label="Finish" value={turn.finish_reason ?? '—'} />
      </dl>

      {turn.truncated && (
        <p
          role="note"
          className="mt-2 rounded border border-warn/30 bg-warn-soft px-2.5 py-1.5 text-[11.5px] text-warn"
        >
          Capture truncated this turn at write time; stored content may be incomplete. This is not a
          display limit.
        </p>
      )}

      <AuditDiffView diff={turn.diff} includeContent={includeContent} />

      {includeContent && contentReady && (
        <AuditContentSections
          messages={turn.request_messages ?? []}
          params={turn.request_params}
          responseContent={turn.response_content}
          responseToolCalls={turn.response_tool_calls}
        />
      )}

      <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2">
        <p
          className="min-w-0 break-all font-mono text-[10.5px] text-ink-muted"
          title={turn.request_id}
        >
          {shortIdentifier(turn.request_id)}
          {turn.parent_request_id !== null && (
            <span className="ml-2 text-ink-muted/80">
              parent {shortIdentifier(turn.parent_request_id)}
            </span>
          )}
        </p>
        <Button
          variant="ghost"
          aria-expanded={requestOpen}
          onClick={() => setRequestOpen((current) => !current)}
          aria-label={
            requestOpen ? `Close request ${turn.request_id}` : `Open request ${turn.request_id}`
          }
          className="px-2 py-0.5 text-[11.5px]"
        >
          {requestOpen ? 'Close request' : 'Open request'}
        </Button>
      </div>

      {requestOpen && (
        <AuditRequestDetail
          masterKey={masterKey}
          requestId={turn.request_id}
          onClose={() => setRequestOpen(false)}
        />
      )}
    </article>
  );
}
