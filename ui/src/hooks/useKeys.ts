import { useQuery } from '@tanstack/react-query';

import { listKeys } from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export interface KeyPage {
  tenantId: string | null;
  limit: number;
  offset: number;
}

export function useKeyPage(masterKey: string | null, page: KeyPage) {
  return useQuery({
    queryKey: queryKeys.keyPage(page.tenantId, page.limit, page.offset),
    queryFn: ({ signal }) => {
      if (masterKey === null) {
        throw new Error('The API key page query started without a master key.');
      }
      return listKeys(masterKey, signal, {
        tenantId: page.tenantId,
        limit: page.limit,
        offset: page.offset,
      });
    },
    enabled: masterKey !== null,
    retry: false,
  });
}

export type KeyPageQuery = ReturnType<typeof useKeyPage>;
