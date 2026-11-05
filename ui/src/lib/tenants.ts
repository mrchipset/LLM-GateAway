export const TENANT_NAME_MAX_LENGTH = 100;

export function validateTenantName(raw: string): string | undefined {
  const trimmed = raw.trim();
  if (trimmed.length === 0) return 'Enter a tenant name.';
  if (trimmed.length > TENANT_NAME_MAX_LENGTH) {
    return `Use ${TENANT_NAME_MAX_LENGTH} characters or fewer.`;
  }
  return undefined;
}
