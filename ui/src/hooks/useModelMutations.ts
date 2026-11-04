import { useMutation, useQueryClient } from '@tanstack/react-query';

import { createModel, deleteModel, type CreateModelInput } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useCreateModel() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateModelInput) => createModel(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.models });
    },
  });
}

export function useDeleteModel() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (modelId: string) => deleteModel(modelId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.models });
    },
  });
}
