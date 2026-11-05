import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createDeployment,
  deleteDeployment,
  listDeployments,
  updateDeployment,
  type CreateDeploymentInput,
  type UpdateDeploymentInput,
} from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useDeployments(modelId: string | null) {
  return useQuery({
    queryKey: queryKeys.deployments(modelId ?? ''),
    queryFn: ({ signal }) => {
      if (modelId === null) {
        throw new Error('The deployments query started without a model id.');
      }
      return listDeployments(modelId, signal);
    },
    enabled: modelId !== null,
    retry: false,
  });
}

export function useCreateDeployment(modelId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateDeploymentInput) => createDeployment(modelId, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.deployments(modelId) });
    },
  });
}

export function useUpdateDeployment(modelId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (args: { deploymentId: string; input: UpdateDeploymentInput }) =>
      updateDeployment(args.deploymentId, args.input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.deployments(modelId) });
    },
  });
}

export function useDeleteDeployment(modelId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (deploymentId: string) => deleteDeployment(deploymentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.deployments(modelId) });
    },
  });
}

export type DeploymentsQuery = ReturnType<typeof useDeployments>;
