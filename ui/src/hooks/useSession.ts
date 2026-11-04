import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getCurrentAdmin, login, logout, type LoginInput } from '../api/client';
import { adminQueryPrefixes, adminSessionKey } from '../lib/queryKeys';

export function useCurrentAdmin() {
  return useQuery({
    queryKey: adminSessionKey,
    queryFn: ({ signal }) => getCurrentAdmin(signal),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: LoginInput) => login(input),
    onSuccess: () => {
      for (const queryKey of adminQueryPrefixes) {
        void queryClient.cancelQueries({ queryKey });
        queryClient.removeQueries({ queryKey });
      }
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => logout(),
    onSettled: () => {
      for (const queryKey of adminQueryPrefixes) {
        void queryClient.cancelQueries({ queryKey });
        queryClient.removeQueries({ queryKey });
      }
      queryClient.getMutationCache().clear();
      queryClient.setQueryData(adminSessionKey, null);
    },
  });
}

export function discardAdminData(queryClient: ReturnType<typeof useQueryClient>): void {
  for (const queryKey of adminQueryPrefixes) {
    void queryClient.cancelQueries({ queryKey });
    queryClient.removeQueries({ queryKey });
  }
  queryClient.setQueryData(adminSessionKey, null);
}
