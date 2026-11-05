export type OptionalCountResult =
  { status: 'empty' } | { status: 'set'; value: number } | { status: 'invalid' };

export type CountChangeResult =
  { status: 'unchanged' } | { status: 'set'; value: number | null } | { status: 'invalid' };

export function countErrorText(min: number): string {
  return `Enter a whole number of ${min} or more.`;
}

/** Formats an optional limit for a form input; `null` and absent both read as blank. */
export function limitToInput(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : String(value);
}

export function parseOptionalCount(raw: string, min: number): OptionalCountResult {
  const value = raw.trim();
  if (value === '') return { status: 'empty' };
  if (!/^\d+$/.test(value)) return { status: 'invalid' };

  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < min) return { status: 'invalid' };
  return { status: 'set', value: parsed };
}

export function parseCountChange(raw: string, original: string, min: number): CountChangeResult {
  const value = raw.trim();
  if (value === original) return { status: 'unchanged' };
  if (value === '') return { status: 'set', value: null };
  if (!/^\d+$/.test(value)) return { status: 'invalid' };

  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < min) return { status: 'invalid' };
  return { status: 'set', value: parsed };
}
