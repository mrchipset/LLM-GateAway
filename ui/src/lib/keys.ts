import type { ApiKeySummary } from '../api/client';

export type KeyStatus = 'Active' | 'Revoked' | 'Expired';

export function apiKeyStatus(key: ApiKeySummary, now: number): KeyStatus {
  if (key.revoked_at !== null) return 'Revoked';
  if (key.expires_at !== null) {
    const expiresAt = Date.parse(key.expires_at);
    if (!Number.isNaN(expiresAt) && expiresAt <= now) return 'Expired';
  }
  return 'Active';
}
