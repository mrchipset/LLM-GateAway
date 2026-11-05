import type { KeyUsageSummary, UsageModelSummary } from '../api/client';

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

export const USAGE_BY_KEY_CSV_COLUMNS = [
  'Key name',
  'Key prefix',
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

function utcMidnightMs(value: string): number {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return Number.NaN;
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
}

export function usageDayKey(value: string): string {
  const midnight = utcMidnightMs(value);
  if (Number.isNaN(midnight)) return value;
  return new Date(midnight).toISOString().slice(0, 10);
}

export interface UsageDayWindow {
  since: string;
  until: string;
}

export function usageDayWindow(value: string): UsageDayWindow {
  const midnight = utcMidnightMs(value);
  if (Number.isNaN(midnight)) {
    throw new Error(`Invalid usage day: ${value}`);
  }

  return {
    since: new Date(midnight).toISOString(),
    until: new Date(midnight + MS_PER_DAY).toISOString(),
  };
}

function csvField(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

function usageCsv(columns: readonly string[], rows: ReadonlyArray<ReadonlyArray<string>>): string {
  return [columns, ...rows].map((row) => row.map(csvField).join(',')).join('\n');
}

export function usageByModelCsv(items: UsageModelSummary[]): string {
  return usageCsv(
    USAGE_BY_MODEL_CSV_COLUMNS,
    items.map((item) => [
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
    ]),
  );
}

type UsageKeyIdentity = Pick<KeyUsageSummary, 'api_key_id' | 'name' | 'key_prefix'>;

export function usageKeyLabel(item: UsageKeyIdentity): string {
  const name = item.name?.trim();
  if (name !== undefined && name.length > 0) return name;

  const prefix = item.key_prefix?.trim();
  if (prefix !== undefined && prefix.length > 0) return prefix;

  return `${item.api_key_id.slice(0, 8)}…`;
}

export function usageByKeyCsv(items: KeyUsageSummary[]): string {
  return usageCsv(
    USAGE_BY_KEY_CSV_COLUMNS,
    items.map((item) => [
      usageKeyLabel(item),
      item.key_prefix ?? '',
      String(item.requests),
      String(item.prompt_tokens),
      String(item.completion_tokens),
      String(item.cached_tokens),
      String(item.total_tokens),
      String(item.covered_tokens),
      String(item.billable_tokens),
      item.billed_cost,
    ]),
  );
}

function dateStamp(value: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(value);
  return match?.[1] ?? value.replace(/[^0-9A-Za-z]+/g, '-');
}

function tenantSlug(tenantId: string | null): string {
  const slug = (tenantId ?? '').replace(/[^0-9A-Za-z._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '');
  return slug === '' ? 'all' : slug;
}

function usageCsvFilename(
  kind: 'model' | 'key',
  tenantId: string | null,
  since: string,
  until: string,
): string {
  return `usage-by-${kind}-${tenantSlug(tenantId)}-${dateStamp(since)}-${dateStamp(until)}.csv`;
}

export function usageByModelFilename(
  tenantId: string | null,
  since: string,
  until: string,
): string {
  return usageCsvFilename('model', tenantId, since, until);
}

export function usageByKeyFilename(tenantId: string | null, since: string, until: string): string {
  return usageCsvFilename('key', tenantId, since, until);
}
