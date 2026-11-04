import type { ReactNode } from 'react';

import { AdminSessionContext, type AdminSessionValue } from '../lib/adminSessionContext';
import { roleCapabilities, type AdminSession } from '../lib/session';

export function AdminSessionProvider({
  session,
  children,
}: {
  session: AdminSession;
  children: ReactNode;
}) {
  const value: AdminSessionValue = { session, ...roleCapabilities(session.role) };
  return <AdminSessionContext.Provider value={value}>{children}</AdminSessionContext.Provider>;
}
