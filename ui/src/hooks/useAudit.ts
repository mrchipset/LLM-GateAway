import { keepPreviousData, useQuery } from '@tanstack/react-query';

import {
  getAuditRequest,
  getAuditSession,
  getAuditSessions,
  listKeys,
  type AuditSessionQuery,
} from '../api/client';
import { queryKeys } from '../lib/queryKeys';

export function useAuditSessions(masterKey: string | null, query: AuditSessionQuery) {
  return useQuery({
    queryKey: queryKeys.auditSessions(query),
    queryFn: ({ signal }) => {
      if (masterKey === null) {
        throw new Error('The audit sessions query started without a master key.');
      }
      return getAuditSessions(masterKey, query, signal);
    },
    enabled: masterKey !== null,
    retry: false,
  });
}

export function useAuditSession(
  masterKey: string | null,
  sessionId: string | null,
  includeContent: boolean,
) {
  return useQuery({
    queryKey: queryKeys.auditSession(sessionId ?? '', includeContent),
    queryFn: ({ signal }) => {
      if (masterKey === null || sessionId === null) {
        throw new Error('The audit session query started without a master key or session.');
      }
      return getAuditSession(masterKey, sessionId, includeContent, signal);
    },
    enabled: masterKey !== null && sessionId !== null,
    retry: false,
    placeholderData: keepPreviousData,
  });
}

export function useAuditRequest(masterKey: string | null, requestId: string | null) {
  return useQuery({
    queryKey: queryKeys.auditRequest(requestId ?? ''),
    queryFn: ({ signal }) => {
      if (masterKey === null || requestId === null) {
        throw new Error('The audit request query started without a master key or request.');
      }
      return getAuditRequest(masterKey, requestId, signal);
    },
    enabled: masterKey !== null && requestId !== null,
    retry: false,
  });
}

export function useAuditKeyOptions(masterKey: string | null, tenantId: string | null) {
  return useQuery({
    queryKey: queryKeys.keyPage(tenantId, 100, 0),
    queryFn: ({ signal }) => {
      if (masterKey === null || tenantId === null) {
        throw new Error('The audit key options query started without a master key or tenant.');
      }
      return listKeys(masterKey, signal, { tenantId, limit: 100, offset: 0 });
    },
    enabled: masterKey !== null && tenantId !== null,
    retry: false,
  });
}

export type AuditSessionsQuery = ReturnType<typeof useAuditSessions>;
export type AuditSessionQueryResult = ReturnType<typeof useAuditSession>;
export type AuditRequestQuery = ReturnType<typeof useAuditRequest>;
export type AuditKeyOptionsQuery = ReturnType<typeof useAuditKeyOptions>;
