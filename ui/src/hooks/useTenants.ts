import { useQuery } from '@tanstack/react-query';

import { listTenants } from '../api/client';

export function useTenants(masterKey: string | null) {
  return useQuery({
    queryKey: ['admin-tenants'],
    queryFn: ({ signal }) => {
      if (masterKey === null) {
        throw new Error('The tenants query started without a master key.');
      }
      return listTenants(masterKey, signal);
    },
    enabled: masterKey !== null,
    retry: false,
  });
}

export type TenantsQuery = ReturnType<typeof useTenants>;
