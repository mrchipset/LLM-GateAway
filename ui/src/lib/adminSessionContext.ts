import { createContext, useContext } from 'react';

import type { AdminSession, RoleCapabilities } from './session';

export interface AdminSessionValue extends RoleCapabilities {
  session: AdminSession;
}

export const AdminSessionContext = createContext<AdminSessionValue | null>(null);

export function useAdminSession(): AdminSessionValue {
  const value = useContext(AdminSessionContext);
  if (value === null) {
    throw new Error('useAdminSession must be used inside AdminSessionProvider');
  }
  return value;
}
