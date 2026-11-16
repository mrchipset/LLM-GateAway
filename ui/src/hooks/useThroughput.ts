import { useQuery } from '@tanstack/react-query';

import { getThroughput } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useThroughput() {
  return useQuery({
    queryKey: queryKeys.throughput,
    queryFn: ({ signal }) => getThroughput(signal),
    refetchInterval: 20_000,
    retry: false,
  });
}

export type ThroughputQuery = ReturnType<typeof useThroughput>;
