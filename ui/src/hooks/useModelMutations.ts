import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  createModel,
  deleteModel,
  updateModel,
  type CreateModelInput,
  type UpdateModelInput,
} from '../api/client';
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

export function useUpdateModel() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: { modelId: string; patch: UpdateModelInput }) =>
      updateModel(input.modelId, input.patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.models });
    },
  });
}
