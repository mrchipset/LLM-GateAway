import { useQuery } from '@tanstack/react-query';

import { listAdminAudit, type AdminAuditQuery } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useAdminAudit(query: AdminAuditQuery) {
  return useQuery({
    queryKey: queryKeys.adminAudit(query),
    queryFn: ({ signal }) => listAdminAudit(query, signal),
    retry: false,
  });
}

export type AdminAuditListQuery = ReturnType<typeof useAdminAudit>;
