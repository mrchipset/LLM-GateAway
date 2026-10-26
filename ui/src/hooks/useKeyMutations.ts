import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';

import { createKey, revokeKey, type CreateApiKeyInput } from '../api/client';
import { queryKeys, usageByKeyPrefix } from '../lib/queryKeys';

const createKeyMutationKey = ['admin-keys', 'create'] as const;

export function useCreateKey(masterKey: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: createKeyMutationKey,
    gcTime: 0,
    mutationFn: (input: CreateApiKeyInput) => createKey(masterKey, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.keys });
    },
  });
}

export function discardCreateKeyMutation(queryClient: QueryClient): void {
  const mutationCache = queryClient.getMutationCache();
  for (const mutation of mutationCache.findAll({ mutationKey: createKeyMutationKey })) {
    mutationCache.remove(mutation);
  }
}

export function useRevokeKey(masterKey: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (keyId: string) => revokeKey(masterKey, keyId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.keys });
      void queryClient.invalidateQueries({ queryKey: usageByKeyPrefix });
    },
  });
}
