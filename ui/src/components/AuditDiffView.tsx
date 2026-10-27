import type { AuditDiff } from '../api/client';
import { formatParamValue, formatShortHash, formatSignedNumber } from '../lib/audit';
import { formatExactNumber } from '../lib/format';

const USAGE_FIELDS = [
  { key: 'prompt_tokens', label: 'Prompt' },
  { key: 'completion_tokens', label: 'Completion' },
  { key: 'cached_tokens', label: 'Cached' },
  { key: 'total_tokens', label: 'Total' },
] as const;

function SectionLabel({ children, aside }: { children: string; aside?: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h5 className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted">
        {children}
      </h5>
      {aside !== undefined && <p className="text-[10.5px] text-ink-muted">{aside}</p>}
    </div>
  );
}

function CountChip({ label, value }: { label: string; value: number }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[10.5px] tabular-nums text-ink">
      <span className="text-ink-muted">{label}</span>
      {formatExactNumber(value)}
    </span>
  );
}

function MessagePreview({ children }: { children: string }) {
  return (
    <p className="mt-0.5 whitespace-pre-wrap break-words font-mono text-[11px] leading-snug text-ink">
      {children.length > 0 ? children : '—'}
    </p>
  );
}

function ChangeList({ diff }: { diff: AuditDiff }) {
  const hasMessages =
    diff.added_messages.length > 0 ||
    diff.modified_messages.length > 0 ||
    diff.removed_messages.length > 0;

  return (
    <section>
      <SectionLabel aside="Bounded excerpts">Message previews</SectionLabel>
      {!hasMessages ? (
        <p className="mt-1 text-[11.5px] text-ink-muted">
          No message additions, edits, or removals.
        </p>
      ) : (
        <ul className="mt-1 space-y-1.5">
          {diff.added_messages.map((message) => (
            <li
              key={`added-${message.index}`}
              className="rounded border border-ok/20 bg-ok-soft/40 px-2 py-1.5"
            >
              <p className="flex flex-wrap items-baseline gap-x-2 font-mono text-[10.5px]">
                <span className="font-medium text-ok">Added</span>
                <span className="text-ink-muted">
                  #{message.index} · {message.role}
                </span>
              </p>
              <MessagePreview>{message.preview}</MessagePreview>
            </li>
          ))}
          {diff.modified_messages.map((message) => (
            <li
              key={`modified-${message.index}`}
              className="rounded border border-warn/25 bg-warn-soft/40 px-2 py-1.5"
            >
              <p className="flex flex-wrap items-baseline gap-x-2 font-mono text-[10.5px]">
                <span className="font-medium text-warn">Modified</span>
                <span className="text-ink-muted">
                  #{message.index} · {message.role}
                </span>
              </p>
              <MessagePreview>{`${message.before_preview} → ${message.after_preview}`}</MessagePreview>
            </li>
          ))}
          {diff.removed_messages.map((message) => (
            <li
              key={`removed-${message.index}`}
              className="rounded border border-danger/20 bg-danger-soft/40 px-2 py-1.5"
            >
              <p className="flex flex-wrap items-baseline gap-x-2 font-mono text-[10.5px]">
                <span className="font-medium text-danger">Removed</span>
                <span className="text-ink-muted">
                  #{message.index} · {message.role}
                </span>
              </p>
              <MessagePreview>{message.preview}</MessagePreview>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ParameterChanges({ diff, includeContent }: { diff: AuditDiff; includeContent: boolean }) {
  const entries = Object.entries(diff.parameter_changes);
  const boundedHint = includeContent
    ? 'Bounded at capture; this value exceeded the content budget.'
    : 'Values are shown as hashes while full content is off. Turn on Show full content to load plaintext; values over the capture cap stay hashed.';

  return (
    <section>
      <SectionLabel>Parameter changes</SectionLabel>
      {entries.length === 0 ? (
        <p className="mt-1 text-[11.5px] text-ink-muted">No parameter changes.</p>
      ) : (
        <dl className="mt-1 space-y-1.5">
          {entries.map(([field, change]) => (
            <div
              key={field}
              className="rounded border border-line bg-surface px-2 py-1.5 font-mono text-[11px]"
            >
              <dt className="break-all text-ink">{field}</dt>
              <dd className="mt-0.5 break-all text-ink-muted">
                {change.kind === 'values' ? (
                  <span>
                    <span className="text-ink">{formatParamValue(change.from)}</span>
                    <span aria-hidden="true"> → </span>
                    <span className="sr-only">to</span>
                    <span className="text-ink">{formatParamValue(change.to)}</span>
                  </span>
                ) : (
                  <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-1">
                    <span title={change.from_hash ?? undefined}>
                      {formatShortHash(change.from_hash)}
                    </span>
                    <span aria-hidden="true">→</span>
                    <span className="sr-only">to</span>
                    <span title={change.to_hash ?? undefined}>
                      {formatShortHash(change.to_hash)}
                    </span>
                    <span
                      title={boundedHint}
                      className="rounded border border-line-strong bg-surface-sunken px-1 py-0.5 text-[10px] text-ink-muted"
                    >
                      bounded
                    </span>
                  </span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

function UsageDelta({ diff }: { diff: AuditDiff }) {
  const present = USAGE_FIELDS.filter(({ key }) => key in diff.usage_delta);

  return (
    <section>
      <SectionLabel>Usage delta</SectionLabel>
      {present.length === 0 ? (
        <p className="mt-1 text-[11.5px] text-ink-muted">No usage delta recorded.</p>
      ) : (
        <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px]">
          {present.map(({ key, label }) => {
            const value = diff.usage_delta[key] ?? 0;
            return (
              <div key={key} className="flex items-baseline gap-1.5">
                <dt className="text-ink-muted">{label}</dt>
                <dd
                  className={`font-mono tabular-nums ${
                    value > 0 ? 'text-ok' : value < 0 ? 'text-danger' : 'text-ink'
                  }`}
                >
                  {formatSignedNumber(value)}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </section>
  );
}

function ResponseChange({ diff }: { diff: AuditDiff }) {
  const change = diff.response_change;
  const finishReason = change.finish_reason_changed
    ? `${change.previous_finish_reason ?? '—'} → ${change.finish_reason ?? '—'}`
    : (change.finish_reason ?? '—');
  const toolNames = change.tool_call_names;

  return (
    <section>
      <SectionLabel>Response change</SectionLabel>
      <dl className="mt-1 grid gap-x-4 gap-y-1 text-[11.5px] sm:grid-cols-[6.5rem_minmax(0,1fr)]">
        <dt className="text-ink-muted">Content</dt>
        <dd className={change.content_changed ? 'text-warn' : 'text-ink'}>
          {change.content_changed ? 'Changed' : 'Unchanged'}
        </dd>
        <dt className="text-ink-muted">Finish reason</dt>
        <dd className="break-words font-mono text-[11px] text-ink">{finishReason}</dd>
        <dt className="text-ink-muted">Tool calls</dt>
        <dd className="text-ink">
          {change.tool_calls_added === 0 &&
          change.tool_calls_removed === 0 &&
          toolNames.length === 0 ? (
            'No tool call changes'
          ) : (
            <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-mono tabular-nums text-ok">
                +{formatExactNumber(change.tool_calls_added)}
              </span>
              <span className="font-mono tabular-nums text-danger">
                -{formatExactNumber(change.tool_calls_removed)}
              </span>
              {toolNames.length > 0 && (
                <span className="break-all font-mono text-[11px] text-ink-muted">
                  {toolNames.join(', ')}
                </span>
              )}
            </span>
          )}
        </dd>
      </dl>
    </section>
  );
}

export function AuditDiffView({
  diff,
  includeContent,
}: {
  diff: AuditDiff | null;
  includeContent: boolean;
}) {
  if (diff === null) {
    return (
      <p className="mt-2 border-t border-line pt-2 text-[11.5px] text-ink-muted">
        No diff was stored for this turn.
      </p>
    );
  }

  return (
    <div className="mt-2.5 space-y-3 border-t border-line pt-2.5">
      <div className="flex flex-wrap items-center gap-1.5" aria-label="Diff counts">
        <CountChip label="Added" value={diff.added_messages.length} />
        <CountChip label="Modified" value={diff.modified_messages.length} />
        <CountChip label="Removed" value={diff.removed_messages.length} />
        <span className="font-mono text-[10.5px] text-ink-muted">
          common prefix: {formatExactNumber(diff.common_prefix)}
        </span>
      </div>
      <ChangeList diff={diff} />
      <ParameterChanges diff={diff} includeContent={includeContent} />
      <UsageDelta diff={diff} />
      <ResponseChange diff={diff} />
    </div>
  );
}
