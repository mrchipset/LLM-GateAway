import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getTenantModelAccess,
  replaceTenantModelAccess,
  type TenantModelAccessInput,
} from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useTenantModelAccess(masterKey: string, tenantId: string) {
  return useQuery({
    queryKey: queryKeys.modelAccess(tenantId),
    queryFn: ({ signal }) => getTenantModelAccess(masterKey, tenantId, signal),
    retry: false,
  });
}

export function useReplaceTenantModelAccess(masterKey: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (args: { tenantId: string; input: TenantModelAccessInput }) =>
      replaceTenantModelAccess(masterKey, args.tenantId, args.input),
    onSuccess: async (_data, args) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tenants }),
        queryClient.invalidateQueries({ queryKey: queryKeys.modelAccess(args.tenantId) }),
      ]);
    },
  });
}
