import { useQuery } from '@tanstack/react-query';

import { getTenantBilling } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useTenantBilling(tenantId: string | null) {
  return useQuery({
    queryKey: queryKeys.tenantBilling(tenantId ?? ''),
    queryFn: ({ signal }) => {
      if (tenantId === null) {
        throw new Error('The tenant billing query started without a tenant id.');
      }
      return getTenantBilling(tenantId, signal);
    },
    enabled: tenantId !== null,
    retry: false,
  });
}

export type TenantBillingQuery = ReturnType<typeof useTenantBilling>;
