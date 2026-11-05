import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  createTenant,
  deleteTenant,
  updateTenantLimits,
  type CreateTenantInput,
  type TenantLimitsPatch,
} from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useCreateTenant() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateTenantInput) => createTenant(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.tenants });
    },
  });
}

export function useUpdateTenantLimits() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (args: { tenantId: string; patch: TenantLimitsPatch }) =>
      updateTenantLimits(args.tenantId, args.patch),
    onSuccess: async (_tenant, args) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tenants }),
        queryClient.invalidateQueries({ queryKey: queryKeys.tenantBilling(args.tenantId) }),
      ]);
    },
  });
}

export function useDeleteTenant() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (tenantId: string) => deleteTenant(tenantId),
    onSuccess: async (_data, tenantId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tenants }),
        // The key page for the deleted tenant would now 404. Its filter is reset
        // by AccessPanel, so leave that query out and refresh every other page.
        queryClient.invalidateQueries({
          queryKey: queryKeys.keys,
          predicate: (query) => keyPageTenantId(query.queryKey) !== tenantId,
        }),
      ]);
    },
  });
}

function keyPageTenantId(queryKey: readonly unknown[]): unknown {
  const params = queryKey[1];
  if (typeof params !== 'object' || params === null || !('tenantId' in params)) return undefined;
  return (params as { tenantId?: unknown }).tenantId;
}
