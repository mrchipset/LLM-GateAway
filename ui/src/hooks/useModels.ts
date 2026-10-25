import { useQuery } from '@tanstack/react-query';

import { listModels } from '../api/client';

export function useModels(masterKey: string | null) {
  return useQuery({
    queryKey: ['admin-models'],
    queryFn: ({ signal }) => {
      if (masterKey === null) {
        throw new Error('The models query started without a master key.');
      }
      return listModels(masterKey, signal);
    },
    enabled: masterKey !== null,
    retry: false,
  });
}

export type ModelsQuery = ReturnType<typeof useModels>;
