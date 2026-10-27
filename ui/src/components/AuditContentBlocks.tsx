import { useState, type ReactNode } from 'react';

import type { AuditMessagePayload, AuditParams } from '../api/client';
import { extractMessageRole, extractMessageText, prettyJson } from '../lib/audit';
import { Button } from './Button';
import { CopyIcon } from './Icons';

const LONG_TEXT_THRESHOLD = 600;

const ROLE_CLASSES: Record<string, string> = {
  system: 'border-line-strong bg-surface-sunken text-ink',
  user: 'border-accent/30 bg-accent/5 text-accent',
  assistant: 'border-ok/25 bg-ok-soft text-ok',
  tool: 'border-warn/30 bg-warn-soft text-warn',
};

interface CopyTextButtonProps {
  text: string;
  label: string;
}

export function CopyTextButton({ text, label }: CopyTextButtonProps) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState('copied');
    } catch {
      setState('failed');
    }
  };

  return (
    <span className="inline-flex items-center gap-1.5">
      <Button
        variant="ghost"
        onClick={() => void handleCopy()}
        aria-label={`Copy ${label}`}
        className="px-1.5 py-0.5 text-[11px]"
      >
        <CopyIcon className="size-3" />
        {state === 'copied' ? 'Copied' : 'Copy'}
      </Button>
      {state === 'failed' && (
        <span role="status" className="text-[10.5px] text-danger">
          Copy failed
        </span>
      )}
    </span>
  );
}

interface LongTextProps {
  text: string;
  label: string;
  className?: string;
}

export function LongText({ text, label, className = '' }: LongTextProps) {
  const isLong = text.length > LONG_TEXT_THRESHOLD;
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`rounded border border-line bg-surface-sunken/40 ${className}`}>
      <pre
        className={`overflow-auto whitespace-pre-wrap break-words px-2.5 py-2 font-mono text-[11.5px] leading-relaxed text-ink ${
          isLong && !expanded ? 'max-h-40' : 'max-h-[32rem]'
        }`}
      >
        {text}
      </pre>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-2 py-1">
        {isLong ? (
          <Button
            variant="ghost"
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
            className="px-1.5 py-0.5 text-[11px]"
          >
            {expanded ? 'Show less' : 'Show more'}
          </Button>
        ) : (
          <span className="text-[10.5px] text-ink-muted">Text</span>
        )}
        <CopyTextButton text={text} label={label} />
      </div>
    </div>
  );
}

interface JsonBlockProps {
  label: string;
  value: unknown;
}

export function JsonBlock({ label, value }: JsonBlockProps) {
  const text = prettyJson(value);
  return (
    <div className="rounded border border-line bg-surface-sunken/40">
      <div className="flex items-center justify-between gap-2 border-b border-line px-2 py-1">
        <span className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted">
          {label}
        </span>
        <CopyTextButton text={text} label={label} />
      </div>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words px-2.5 py-2 font-mono text-[11px] leading-relaxed text-ink">
        {text}
      </pre>
    </div>
  );
}

function roleClassName(role: string): string {
  return ROLE_CLASSES[role] ?? 'border-line bg-surface-sunken text-ink';
}

function hasValue(value: unknown): boolean {
  return Array.isArray(value) ? value.length > 0 : value !== null && value !== undefined;
}

function MessageItem({ message, index }: { message: AuditMessagePayload; index: number }) {
  const role = extractMessageRole(message);
  const text = extractMessageText(message);
  const name = typeof message.name === 'string' ? message.name : null;
  const toolCallId = typeof message.tool_call_id === 'string' ? message.tool_call_id : null;
  const toolCalls = message.tool_calls;

  return (
    <li className="rounded-md border border-line bg-surface px-2.5 py-2">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span
          className={`inline-flex rounded border px-1.5 py-0.5 font-mono text-[10.5px] font-medium ${roleClassName(role)}`}
        >
          {role}
        </span>
        <span className="font-mono text-[10.5px] text-ink-muted">#{index}</span>
        {name !== null && (
          <span className="font-mono text-[10.5px] text-ink-muted">name: {name}</span>
        )}
        {toolCallId !== null && (
          <span className="break-all font-mono text-[10.5px] text-ink-muted">
            tool_call_id: {toolCallId}
          </span>
        )}
      </div>
      {text.length > 0 ? (
        <LongText text={text} label={`message ${index}`} className="mt-1.5" />
      ) : (
        <p className="mt-1.5 text-[11.5px] text-ink-muted">No text content.</p>
      )}
      {hasValue(toolCalls) && (
        <div className="mt-1.5">
          <JsonBlock label="Message tool calls" value={toolCalls} />
        </div>
      )}
    </li>
  );
}

export function RequestMessages({ messages }: { messages: AuditMessagePayload[] }) {
  if (messages.length === 0) {
    return <p className="text-[12px] text-ink-muted">No request messages were stored.</p>;
  }

  return (
    <ol aria-label="Request messages" className="space-y-2">
      {messages.map((message, index) => (
        <MessageItem key={index} message={message} index={index} />
      ))}
    </ol>
  );
}

function ContentHeading({ children }: { children: ReactNode }) {
  return (
    <h5 className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted">
      {children}
    </h5>
  );
}

interface AuditContentSectionsProps {
  messages: AuditMessagePayload[];
  params: AuditParams | null;
  responseContent: string | null;
  responseToolCalls: AuditMessagePayload[] | null;
}

export function AuditContentSections({
  messages,
  params,
  responseContent,
  responseToolCalls,
}: AuditContentSectionsProps) {
  const toolCalls = responseToolCalls ?? [];

  return (
    <div className="mt-3 space-y-3 rounded-md border border-line bg-surface-sunken/30 p-2.5">
      <p className="text-[11px] text-ink-muted">
        Full content fetched for this view. It is not written to browser storage.
      </p>

      <section aria-label="Request content">
        <ContentHeading>Request messages · {messages.length}</ContentHeading>
        <div className="mt-1.5">
          <RequestMessages messages={messages} />
        </div>
      </section>

      {params !== null && (
        <section aria-label="Request parameters">
          <ContentHeading>Request parameters</ContentHeading>
          <div className="mt-1.5">
            <JsonBlock label="Request parameters" value={params} />
          </div>
        </section>
      )}

      <section aria-label="Response content">
        <ContentHeading>Response content</ContentHeading>
        <div className="mt-1.5">
          {responseContent !== null && responseContent.length > 0 ? (
            <LongText text={responseContent} label="response content" />
          ) : (
            <p className="text-[12px] text-ink-muted">No response content was stored.</p>
          )}
        </div>
      </section>

      <section aria-label="Response tool calls">
        <ContentHeading>Response tool calls · {toolCalls.length}</ContentHeading>
        <div className="mt-1.5">
          {toolCalls.length > 0 ? (
            <JsonBlock label="Response tool calls" value={toolCalls} />
          ) : (
            <p className="text-[12px] text-ink-muted">No response tool calls were stored.</p>
          )}
        </div>
      </section>
    </div>
  );
}
