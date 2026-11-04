import { useQuery } from '@tanstack/react-query';

import { listModelPrices } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useModelPrices(modelId: string | null) {
  return useQuery({
    queryKey: queryKeys.modelPrices(modelId ?? ''),
    queryFn: ({ signal }) => {
      if (modelId === null) {
        throw new Error('The model prices query started without a model id.');
      }
      return listModelPrices(modelId, signal);
    },
    enabled: modelId !== null,
    retry: false,
  });
}

export type ModelPricesQuery = ReturnType<typeof useModelPrices>;
