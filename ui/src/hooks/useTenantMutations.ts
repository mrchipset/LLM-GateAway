import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  createTenant,
  updateTenantLimits,
  type CreateTenantInput,
  type TenantLimitsPatch,
} from '../api/client';

const TENANTS_QUERY_PREFIX = ['admin-tenants'];

export function useCreateTenant(masterKey: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateTenantInput) => createTenant(masterKey, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: TENANTS_QUERY_PREFIX });
    },
  });
}

export function useUpdateTenantLimits(masterKey: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (args: { tenantId: string; patch: TenantLimitsPatch }) =>
      updateTenantLimits(masterKey, args.tenantId, args.patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: TENANTS_QUERY_PREFIX });
    },
  });
}
