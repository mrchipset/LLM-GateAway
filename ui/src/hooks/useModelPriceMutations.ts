import { useMutation, useQueryClient } from '@tanstack/react-query';

import { createModelPrice, type CreateModelPriceInput } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useCreateModelPrice() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (args: { modelId: string; input: CreateModelPriceInput }) =>
      createModelPrice(args.modelId, args.input),
    onSuccess: async (_price, args) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.modelPrices(args.modelId) });
    },
  });
}
