import { useQuery } from '@tanstack/react-query';

import { listTenants } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export const TENANT_SELECTOR_LIMIT = 100;

export interface TenantPage {
  limit: number;
  offset: number;
}

export function useTenants() {
  return useQuery({
    queryKey: queryKeys.tenantPage(TENANT_SELECTOR_LIMIT, 0),
    queryFn: ({ signal }) => listTenants(signal, { limit: TENANT_SELECTOR_LIMIT, offset: 0 }),
    retry: false,
  });
}

export function useTenantPage(page: TenantPage) {
  return useQuery({
    queryKey: queryKeys.tenantPage(page.limit, page.offset),
    queryFn: ({ signal }) => listTenants(signal, { limit: page.limit, offset: page.offset }),
    retry: false,
  });
}

export type TenantsQuery = ReturnType<typeof useTenants>;
export type TenantPageQuery = ReturnType<typeof useTenantPage>;
