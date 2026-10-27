import {
  ApiRequestError,
  type AuditChangeType,
  type AuditMatchMethod,
  type AuditMessagePayload,
  type AuditStatus,
} from '../api/client';
import { formatExactNumber } from './format';
import { USAGE_RANGE_PRESETS, usageRangeSinceIso, type UsageRangeDays } from './usage';

export const AUDIT_PAGE_SIZE = 20;
export const AUDIT_RANGE_PRESETS = USAGE_RANGE_PRESETS;
export type AuditRangeDays = UsageRangeDays;
export const DEFAULT_AUDIT_RANGE_DAYS: AuditRangeDays = 30;

export function auditRangeSinceIso(days: AuditRangeDays, anchor: Date = new Date()): string {
  return usageRangeSinceIso(days, anchor);
}

export const CHANGE_TYPE_META: Record<AuditChangeType, { label: string; className: string }> = {
  new_session: {
    label: 'New session',
    className: 'border-accent/30 bg-accent/5 text-accent',
  },
  continuation: {
    label: 'Continuation',
    className: 'border-ok/25 bg-ok-soft text-ok',
  },
  regeneration: {
    label: 'Regeneration',
    className: 'border-warn/30 bg-warn-soft text-warn',
  },
  edit: {
    label: 'Edit',
    className: 'border-line-strong bg-surface-sunken text-ink',
  },
  truncation: {
    label: 'Truncation',
    className: 'border-danger/25 bg-danger-soft text-danger',
  },
};

export const STATUS_META: Record<AuditStatus, { label: string; className: string }> = {
  completed: {
    label: 'Completed',
    className: 'border-ok/25 bg-ok-soft text-ok',
  },
  upstream_error: {
    label: 'Upstream error',
    className: 'border-danger/25 bg-danger-soft text-danger',
  },
  client_error: {
    label: 'Client error',
    className: 'border-warn/30 bg-warn-soft text-warn',
  },
  client_disconnected: {
    label: 'Client disconnected',
    className: 'border-warn/30 bg-warn-soft text-warn',
  },
  error: {
    label: 'Error',
    className: 'border-danger/25 bg-danger-soft text-danger',
  },
};

export const MATCH_METHOD_LABEL: Record<AuditMatchMethod, string> = {
  explicit: 'Explicit',
  prefix: 'Prefix',
  new: 'New',
};

export function shortIdentifier(value: string): string {
  if (value.length <= 12) return value;
  return `${value.slice(0, 8)}…`;
}

export function auditSessionTitle(titlePreview: string): string {
  const trimmed = titlePreview.trim();
  return trimmed.length > 0 ? trimmed : 'Untitled session';
}

export function formatSignedNumber(value: number): string {
  if (value === 0) return '0';
  return `${value > 0 ? '+' : '-'}${formatExactNumber(Math.abs(value))}`;
}

export function formatShortHash(hash: string | null): string {
  if (hash === null || hash.length === 0) return '—';
  if (hash.length <= 12) return hash;
  return `${hash.slice(0, 10)}…`;
}

export function formatParamValue(value: unknown): string {
  if (value === undefined) return '—';
  if (value === null) return 'null';
  if (typeof value === 'string') return value.length === 0 ? '""' : value;
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }
  try {
    const json = JSON.stringify(value);
    return json === undefined ? String(value) : json;
  } catch {
    return String(value);
  }
}

export function prettyJson(value: unknown): string {
  try {
    const json = JSON.stringify(value, null, 2);
    return json === undefined ? '' : json;
  } catch {
    return '';
  }
}

export function extractMessageRole(message: AuditMessagePayload): string {
  const role = message.role;
  return typeof role === 'string' && role.length > 0 ? role : 'unknown';
}

export function extractMessageText(message: AuditMessagePayload): string {
  const content = message.content;
  if (typeof content === 'string') return content;
  if (content === null || content === undefined) return '';
  if (!Array.isArray(content)) return formatParamValue(content);

  const parts: string[] = [];
  for (const part of content) {
    if (typeof part === 'string') {
      parts.push(part);
      continue;
    }
    if (typeof part === 'object' && part !== null && !Array.isArray(part)) {
      const record = part as Record<string, unknown>;
      if (typeof record.text === 'string') {
        parts.push(record.text);
        continue;
      }
      if (record.type === 'image_url') {
        parts.push('[image]');
        continue;
      }
    }
    parts.push(formatParamValue(part));
  }
  return parts.join('\n');
}

export function isContentTooLarge(error: Error): boolean {
  return (
    error instanceof ApiRequestError &&
    (error.status === 413 || error.code === 'audit_content_too_large')
  );
}
