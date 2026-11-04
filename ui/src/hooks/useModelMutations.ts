import { useMutation, useQueryClient } from '@tanstack/react-query';

import { createModel, deleteModel, type CreateModelInput } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useCreateModel(masterKey: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateModelInput) => createModel(masterKey, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.models });
    },
  });
}

export function useDeleteModel(masterKey: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (modelId: string) => deleteModel(masterKey, modelId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.models });
    },
  });
}
