import type { AuditSessionQuery } from '../api/client';

const modelsPrefix = ['admin-models'] as const;
const tenantsPrefix = ['admin-tenants'] as const;
const keysPrefix = ['admin-keys'] as const;

export const usageSummaryPrefix = ['usage-summary'] as const;
export const usageSeriesPrefix = ['usage-series'] as const;
export const usageByKeyPrefix = ['usage-by-key'] as const;

export const auditSessionsPrefix = ['audit-sessions'] as const;
export const auditSessionPrefix = ['audit-session'] as const;
export const auditRequestPrefix = ['audit-request'] as const;

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
  auditSessions: (query: AuditSessionQuery) =>
    [
      ...auditSessionsPrefix,
      {
        tenantId: query.tenantId,
        apiKeyId: query.apiKeyId,
        modelId: query.modelId,
        q: query.q,
        since: query.since,
        until: query.until ?? null,
        limit: query.limit,
        offset: query.offset,
      },
    ] as const,
  auditSession: (sessionId: string, includeContent: boolean) =>
    [...auditSessionPrefix, sessionId, includeContent] as const,
  auditRequest: (requestId: string) => [...auditRequestPrefix, requestId] as const,
};

export const adminQueryPrefixes = [
  modelsPrefix,
  tenantsPrefix,
  usageSummaryPrefix,
  usageSeriesPrefix,
  usageByKeyPrefix,
  keysPrefix,
  auditSessionsPrefix,
  auditSessionPrefix,
  auditRequestPrefix,
] as const;
