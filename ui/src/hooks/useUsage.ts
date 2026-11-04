import { useQuery } from '@tanstack/react-query';

import { getUsageByKey, getUsageSeries, getUsageSummary, type UsageWindow } from '../api/client';
import { queryKeys } from '../lib/queryKeys';
import { USAGE_BY_KEY_LIMIT } from '../lib/usage';

export function useUsageSummary(window: UsageWindow) {
  return useQuery({
    queryKey: queryKeys.usageSummary(window.tenantId, window.since),
    queryFn: ({ signal }) => getUsageSummary(window, signal),
    retry: false,
  });
}

export function useUsageSeries(window: UsageWindow) {
  return useQuery({
    queryKey: queryKeys.usageSeries(window.tenantId, window.since),
    queryFn: ({ signal }) => getUsageSeries(window, signal),
    retry: false,
  });
}

export function useUsageByKey(window: UsageWindow, limit = USAGE_BY_KEY_LIMIT) {
  return useQuery({
    queryKey: queryKeys.usageByKey(window.tenantId, window.since, limit),
    queryFn: ({ signal }) => getUsageByKey(window, signal, limit),
    retry: false,
  });
}

export type UsageSummaryQuery = ReturnType<typeof useUsageSummary>;
export type UsageSeriesQuery = ReturnType<typeof useUsageSeries>;
export type UsageByKeyQuery = ReturnType<typeof useUsageByKey>;
