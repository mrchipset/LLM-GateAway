import { useQuery } from '@tanstack/react-query';

import { listTenants } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export const TENANT_SELECTOR_LIMIT = 100;

export interface TenantPage {
  limit: number;
  offset: number;
}

export function useTenants(masterKey: string | null) {
  return useQuery({
    queryKey: queryKeys.tenantPage(TENANT_SELECTOR_LIMIT, 0),
    queryFn: ({ signal }) => {
      if (masterKey === null) {
        throw new Error('The tenants query started without a master key.');
      }
      return listTenants(masterKey, signal, { limit: TENANT_SELECTOR_LIMIT, offset: 0 });
    },
    enabled: masterKey !== null,
    retry: false,
  });
}

export function useTenantPage(masterKey: string | null, page: TenantPage) {
  return useQuery({
    queryKey: queryKeys.tenantPage(page.limit, page.offset),
    queryFn: ({ signal }) => {
      if (masterKey === null) {
        throw new Error('The tenant page query started without a master key.');
      }
      return listTenants(masterKey, signal, { limit: page.limit, offset: page.offset });
    },
    enabled: masterKey !== null,
    retry: false,
  });
}

export type TenantsQuery = ReturnType<typeof useTenants>;
export type TenantPageQuery = ReturnType<typeof useTenantPage>;
