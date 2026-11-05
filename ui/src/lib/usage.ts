import type { UsageModelSummary } from '../api/client';

export const USAGE_RANGE_PRESETS = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
] as const;

export type UsageRangeDays = (typeof USAGE_RANGE_PRESETS)[number]['days'];

export const DEFAULT_USAGE_RANGE_DAYS: UsageRangeDays = 30;
export const USAGE_BY_KEY_LIMIT = 100;

export const USAGE_BY_MODEL_CSV_COLUMNS = [
  'Model',
  'Provider',
  'Requests',
  'Prompt',
  'Completion',
  'Cached',
  'Total',
  'Covered',
  'Billable',
  'Billed cost',
] as const;

const MS_PER_DAY = 86_400_000;

export function usageRangeSinceIso(days: UsageRangeDays, anchor: Date = new Date()): string {
  const anchorMidnight = Date.UTC(
    anchor.getUTCFullYear(),
    anchor.getUTCMonth(),
    anchor.getUTCDate(),
  );
  return new Date(anchorMidnight - days * MS_PER_DAY).toISOString();
}

function csvField(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

export function usageByModelCsv(items: UsageModelSummary[]): string {
  const rows = items.map((item) => [
    item.model_id,
    item.provider,
    String(item.requests),
    String(item.prompt_tokens),
    String(item.completion_tokens),
    String(item.cached_tokens),
    String(item.total_tokens),
    String(item.covered_tokens),
    String(item.billable_tokens),
    item.billed_cost,
  ]);

  return [USAGE_BY_MODEL_CSV_COLUMNS, ...rows].map((row) => row.map(csvField).join(',')).join('\n');
}

function dateStamp(value: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(value);
  return match?.[1] ?? value.replace(/[^0-9A-Za-z]+/g, '-');
}

function tenantSlug(tenantId: string | null): string {
  const slug = (tenantId ?? '').replace(/[^0-9A-Za-z._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '');
  return slug === '' ? 'all' : slug;
}

export function usageByModelFilename(
  tenantId: string | null,
  since: string,
  until: string,
): string {
  return `usage-by-model-${tenantSlug(tenantId)}-${dateStamp(since)}-${dateStamp(until)}.csv`;
}
