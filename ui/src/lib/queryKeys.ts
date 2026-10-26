const modelsPrefix = ['admin-models'] as const;
const tenantsPrefix = ['admin-tenants'] as const;
const keysPrefix = ['admin-keys'] as const;

export const usageSummaryPrefix = ['usage-summary'] as const;
export const usageSeriesPrefix = ['usage-series'] as const;
export const usageByKeyPrefix = ['usage-by-key'] as const;

export const queryKeys = {
  models: modelsPrefix,
  tenants: tenantsPrefix,
  tenantPage: (limit: number, offset: number) => [...tenantsPrefix, { limit, offset }] as const,
  usageSummary: (tenantId: string | null, since: string) =>
    [...usageSummaryPrefix, tenantId, since] as const,
  usageSeries: (tenantId: string | null, since: string) =>
    [...usageSeriesPrefix, tenantId, since] as const,
  usageByKey: (tenantId: string | null, since: string, limit: number) =>
    [...usageByKeyPrefix, tenantId, since, limit] as const,
  keys: keysPrefix,
  keyPage: (tenantId: string | null, limit: number, offset: number) =>
    [...keysPrefix, { tenantId, limit, offset }] as const,
};

export const adminQueryPrefixes = [
  modelsPrefix,
  tenantsPrefix,
  usageSummaryPrefix,
  usageSeriesPrefix,
  usageByKeyPrefix,
  keysPrefix,
] as const;
