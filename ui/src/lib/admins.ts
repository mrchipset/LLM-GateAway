export const ADMIN_USERNAME_MIN_LENGTH = 3;
export const ADMIN_USERNAME_MAX_LENGTH = 64;
export const ADMIN_PASSWORD_MIN_LENGTH = 12;
export const ADMIN_PASSWORD_MAX_LENGTH = 256;
export const ADMIN_DISPLAY_NAME_MAX_LENGTH = 100;

const USERNAME_PATTERN = /^[a-z0-9._-]+$/;

export interface AdminDraft {
  username: string;
  displayName: string;
  password: string;
}

export interface AdminDraftErrors {
  username?: string;
  displayName?: string;
  password?: string;
}

export function validateAdminDraft(draft: AdminDraft): AdminDraftErrors {
  const errors: AdminDraftErrors = {};
  const username = draft.username.trim();
  const displayName = draft.displayName.trim();

  if (username.length === 0) {
    errors.username = 'Enter a username.';
  } else if (username.length < ADMIN_USERNAME_MIN_LENGTH) {
    errors.username = `Use at least ${ADMIN_USERNAME_MIN_LENGTH} characters.`;
  } else if (username.length > ADMIN_USERNAME_MAX_LENGTH) {
    errors.username = `Use ${ADMIN_USERNAME_MAX_LENGTH} characters or fewer.`;
  } else if (!USERNAME_PATTERN.test(username)) {
    errors.username = 'Use only lowercase letters, numbers, and . _ -';
  }

  if (displayName.length === 0) {
    errors.displayName = 'Enter a display name.';
  } else if (displayName.length > ADMIN_DISPLAY_NAME_MAX_LENGTH) {
    errors.displayName = `Use ${ADMIN_DISPLAY_NAME_MAX_LENGTH} characters or fewer.`;
  }

  if (draft.password.length < ADMIN_PASSWORD_MIN_LENGTH) {
    errors.password = `Use at least ${ADMIN_PASSWORD_MIN_LENGTH} characters.`;
  } else if (draft.password.length > ADMIN_PASSWORD_MAX_LENGTH) {
    errors.password = `Use ${ADMIN_PASSWORD_MAX_LENGTH} characters or fewer.`;
  }

  return errors;
}

export function hasDraftErrors(errors: AdminDraftErrors): boolean {
  return (
    errors.username !== undefined ||
    errors.displayName !== undefined ||
    errors.password !== undefined
  );
}

export const ADMIN_ROLE_HELP: Record<'owner' | 'operator' | 'auditor', string> = {
  owner: 'Everything, including admin accounts and the admin audit trail.',
  operator: 'Tenants, keys, models, prices, and access. No admin management or audit.',
  auditor: 'Read-only across configuration and audit history.',
};

export const ADMIN_ROLE_OPTIONS = [
  { value: 'owner' as const, label: 'Owner' },
  { value: 'operator' as const, label: 'Operator' },
  { value: 'auditor' as const, label: 'Auditor' },
];
