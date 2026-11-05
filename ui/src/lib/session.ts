export type AdminRole = 'owner' | 'operator' | 'auditor';
export type AdminActorType = 'admin' | 'master' | 'bootstrap';

export interface AdminSession {
  actor_type: AdminActorType;
  name: string;
  role: AdminRole;
  admin_id: string | null;
  session_expires_at: string | null;
}

export interface RoleCapabilities {
  canWrite: boolean;
  canManageAdmins: boolean;
  canReadAudit: boolean;
  canDeleteAudit: boolean;
}

export const CSRF_COOKIE = 'gw_admin_csrf';
export const SESSION_COOKIE = 'gw_admin_session';

const UNSAFE_METHODS = new Set(['POST', 'PATCH', 'PUT', 'DELETE']);

export function roleCapabilities(role: AdminRole): RoleCapabilities {
  return {
    canWrite: role === 'owner' || role === 'operator',
    canManageAdmins: role === 'owner',
    canReadAudit: role === 'owner' || role === 'auditor',
    canDeleteAudit: role === 'owner',
  };
}

export function isUnsafeMethod(method: string | undefined): boolean {
  return method !== undefined && UNSAFE_METHODS.has(method.toUpperCase());
}

export function readCookie(name: string): string | null {
  for (const chunk of document.cookie.split(';')) {
    const separator = chunk.indexOf('=');
    if (separator === -1) continue;
    if (chunk.slice(0, separator).trim() !== name) continue;
    return decodeURIComponent(chunk.slice(separator + 1).trim());
  }
  return null;
}

export function readCsrfToken(): string | null {
  return readCookie(CSRF_COOKIE);
}

export function clearCsrfCookie(): void {
  document.cookie = `${CSRF_COOKIE}=; Max-Age=0; path=/`;
}

type UnauthorizedListener = () => void;

const unauthorizedListeners = new Set<UnauthorizedListener>();

/**
 * Every admin call funnels through one place, so a 401 there can reset the whole
 * console instead of leaving a half-loaded workspace with a rejected request.
 */
export function reportUnauthorized(): void {
  for (const listener of unauthorizedListeners) listener();
}

export function subscribeUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}

export const ROLE_LABELS: Record<AdminRole, string> = {
  owner: 'Owner',
  operator: 'Operator',
  auditor: 'Auditor',
};

export const ROLE_SUMMARIES: Record<AdminRole, string> = {
  owner: 'Manages admins, configuration, and the admin audit trail.',
  operator: 'Manages tenants, keys, models, prices, and access rules.',
  auditor: 'Reads configuration, usage, and audit history. Cannot change anything.',
};
