import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  createTenant,
  updateTenantLimits,
  type CreateTenantInput,
  type TenantLimitsPatch,
} from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useCreateTenant(masterKey: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateTenantInput) => createTenant(masterKey, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.tenants });
    },
  });
}

export function useUpdateTenantLimits(masterKey: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (args: { tenantId: string; patch: TenantLimitsPatch }) =>
      updateTenantLimits(masterKey, args.tenantId, args.patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.tenants });
    },
  });
}
