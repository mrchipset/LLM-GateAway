import { useQuery } from '@tanstack/react-query';

import { listModels } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useModels() {
  return useQuery({
    queryKey: queryKeys.models,
    queryFn: ({ signal }) => listModels(signal),
    retry: false,
  });
}

export type ModelsQuery = ReturnType<typeof useModels>;
