import { useQuery } from '@tanstack/react-query';

import { getTenantBilling } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useTenantBilling(masterKey: string | null, tenantId: string | null) {
  return useQuery({
    queryKey: queryKeys.tenantBilling(tenantId ?? ''),
    queryFn: ({ signal }) => {
      if (masterKey === null || tenantId === null) {
        throw new Error('The tenant billing query started without a master key or tenant id.');
      }
      return getTenantBilling(masterKey, tenantId, signal);
    },
    enabled: masterKey !== null && tenantId !== null,
    retry: false,
  });
}

export type TenantBillingQuery = ReturnType<typeof useTenantBilling>;
