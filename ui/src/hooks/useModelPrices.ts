import { useQuery } from '@tanstack/react-query';

import { listModelPrices } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useModelPrices(masterKey: string | null, modelId: string | null) {
  return useQuery({
    queryKey: queryKeys.modelPrices(modelId ?? ''),
    queryFn: ({ signal }) => {
      if (masterKey === null || modelId === null) {
        throw new Error('The model prices query started without a master key or model id.');
      }
      return listModelPrices(masterKey, modelId, signal);
    },
    enabled: masterKey !== null && modelId !== null,
    retry: false,
  });
}

export type ModelPricesQuery = ReturnType<typeof useModelPrices>;
