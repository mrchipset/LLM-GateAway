import { useQuery } from '@tanstack/react-query';

import { listKeys } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export interface KeyPage {
  tenantId: string | null;
  limit: number;
  offset: number;
}

export function useKeyPage(page: KeyPage) {
  return useQuery({
    queryKey: queryKeys.keyPage(page.tenantId, page.limit, page.offset),
    queryFn: ({ signal }) =>
      listKeys(signal, {
        tenantId: page.tenantId,
        limit: page.limit,
        offset: page.offset,
      }),
    retry: false,
  });
}

export type KeyPageQuery = ReturnType<typeof useKeyPage>;
