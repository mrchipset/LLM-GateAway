import { useQuery } from '@tanstack/react-query';

import { getUsageByKey, getUsageSeries, getUsageSummary, type UsageWindow } from '../api/client';
import { USAGE_BY_KEY_LIMIT } from '../lib/usage';

export function useUsageSummary(masterKey: string | null, window: UsageWindow) {
  return useQuery({
    queryKey: ['usage-summary', window.tenantId, window.since],
    queryFn: ({ signal }) => {
      if (masterKey === null) {
        throw new Error('The usage summary query started without a master key.');
      }
      return getUsageSummary(masterKey, window, signal);
    },
    enabled: masterKey !== null,
    retry: false,
  });
}

export function useUsageSeries(masterKey: string | null, window: UsageWindow) {
  return useQuery({
    queryKey: ['usage-series', window.tenantId, window.since],
    queryFn: ({ signal }) => {
      if (masterKey === null) {
        throw new Error('The usage series query started without a master key.');
      }
      return getUsageSeries(masterKey, window, signal);
    },
    enabled: masterKey !== null,
    retry: false,
  });
}

export function useUsageByKey(
  masterKey: string | null,
  window: UsageWindow,
  limit = USAGE_BY_KEY_LIMIT,
) {
  return useQuery({
    queryKey: ['usage-by-key', window.tenantId, window.since, limit],
    queryFn: ({ signal }) => {
      if (masterKey === null) {
        throw new Error('The usage by key query started without a master key.');
      }
      return getUsageByKey(masterKey, window, signal, limit);
    },
    enabled: masterKey !== null,
    retry: false,
  });
}

export type UsageSummaryQuery = ReturnType<typeof useUsageSummary>;
export type UsageSeriesQuery = ReturnType<typeof useUsageSeries>;
export type UsageByKeyQuery = ReturnType<typeof useUsageByKey>;
