export const USAGE_RANGE_PRESETS = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
] as const;

export type UsageRangeDays = (typeof USAGE_RANGE_PRESETS)[number]['days'];

export const DEFAULT_USAGE_RANGE_DAYS: UsageRangeDays = 30;
export const USAGE_BY_KEY_LIMIT = 100;

const MS_PER_DAY = 86_400_000;

export function usageRangeSinceIso(days: UsageRangeDays, anchor: Date = new Date()): string {
  const anchorMidnight = Date.UTC(
    anchor.getUTCFullYear(),
    anchor.getUTCMonth(),
    anchor.getUTCDate(),
  );
  return new Date(anchorMidnight - days * MS_PER_DAY).toISOString();
}
