const SECRET_FIELD =
  /^(password|passwd|password_hash|secret|session_token|access_token|refresh_token|csrf|csrf_token|credential|credentials|api_key|private_key)$/i;
const SECRET_FIELD_SUFFIX = /(_password|_secret|_token|_credential)$/i;
const SECRET_VALUE = /^(sk-|lgw_|mk_)/i;
const MAX_VALUE_LENGTH = 72;

export const ADMIN_AUDIT_ACTION_OPTIONS = [
  'admin.bootstrap_created',
  'admin.created',
  'admin.updated',
  'api_key.created',
  'api_key.revoked',
  'model.created',
  'model.deleted',
  'model_price.created',
  'tenant.created',
  'tenant.model_access.updated',
  'tenant.updated',
] as const;

export const ADMIN_AUDIT_TARGET_TYPES = ['admin', 'api_key', 'model', 'tenant'] as const;

export interface AdminAuditChange {
  field: string;
  from: string | null;
  to: string | null;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return 'none';
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') {
    const trimmed =
      value.length > MAX_VALUE_LENGTH ? `${value.slice(0, MAX_VALUE_LENGTH)}…` : value;
    return trimmed;
  }
  try {
    const encoded = JSON.stringify(value);
    if (encoded === undefined) return '—';
    return encoded.length > MAX_VALUE_LENGTH ? `${encoded.slice(0, MAX_VALUE_LENGTH)}…` : encoded;
  } catch {
    return '—';
  }
}

function isSecret(field: string, value: unknown): boolean {
  if (SECRET_FIELD.test(field) || SECRET_FIELD_SUFFIX.test(field)) return true;
  return typeof value === 'string' && SECRET_VALUE.test(value);
}

/**
 * Admin audit payloads hold business fields only, but the console stays defensive:
 * anything that smells like a credential is never rendered.
 */
export function adminAuditChanges(
  before: Record<string, unknown> | null,
  after: Record<string, unknown> | null,
): AdminAuditChange[] {
  if (before === null && after === null) return [];

  const fields: string[] = [];
  for (const source of [after, before]) {
    if (source === null) continue;
    for (const field of Object.keys(source)) {
      if (!fields.includes(field)) fields.push(field);
    }
  }

  const changes: AdminAuditChange[] = [];
  for (const field of fields) {
    const beforeValue = before?.[field];
    const afterValue = after?.[field];
    if (isSecret(field, beforeValue) || isSecret(field, afterValue)) continue;

    const hasBefore = before !== null && field in before;
    const hasAfter = after !== null && field in after;
    if (!hasBefore && !hasAfter) continue;

    if (hasBefore && hasAfter && formatValue(beforeValue) === formatValue(afterValue)) {
      continue;
    }

    changes.push({
      field,
      from: hasBefore ? formatValue(beforeValue) : null,
      to: hasAfter ? formatValue(afterValue) : null,
    });
  }

  return changes;
}
