import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  createTenant,
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
