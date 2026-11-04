import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getTenantModelAccess,
  replaceTenantModelAccess,
  type TenantModelAccessInput,
} from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useTenantModelAccess(tenantId: string) {
  return useQuery({
    queryKey: queryKeys.modelAccess(tenantId),
    queryFn: ({ signal }) => getTenantModelAccess(tenantId, signal),
    retry: false,
  });
}

export function useReplaceTenantModelAccess() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (args: { tenantId: string; input: TenantModelAccessInput }) =>
      replaceTenantModelAccess(args.tenantId, args.input),
    onSuccess: async (_data, args) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.tenants }),
        queryClient.invalidateQueries({ queryKey: queryKeys.modelAccess(args.tenantId) }),
      ]);
    },
  });
}
