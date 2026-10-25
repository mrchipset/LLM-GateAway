const createdAtFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC',
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const updatedAtFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const exactNumberFormatter = new Intl.NumberFormat('en-US');

const compactNumberFormatter = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 1,
});

const usageDayFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC',
  year: 'numeric',
  month: 'short',
  day: 'numeric',
});

const usageAxisFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC',
  month: 'short',
  day: 'numeric',
});

export function formatCreatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Invalid date';
  return `${createdAtFormatter.format(date)} UTC`;
}

export function formatUpdatedAt(epochMs: number): string {
  return `${updatedAtFormatter.format(new Date(epochMs))} UTC`;
}

export function formatExactNumber(value: number): string {
  return exactNumberFormatter.format(value);
}

export function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value)) return '—';
  if (Math.abs(value) < 1000) return exactNumberFormatter.format(value);
  return compactNumberFormatter.format(value);
}

export function formatUsageDay(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Invalid date';
  return usageDayFormatter.format(date);
}

export function formatUsageAxis(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Invalid date';
  return usageAxisFormatter.format(date);
}
