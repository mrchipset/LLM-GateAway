import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  deleteAuditRequests,
  exportAuditRequests,
  getAuditRequest,
  getAuditSession,
  getAuditSessions,
  listKeys,
  type AuditDeleteQuery,
  type AuditExportQuery,
  type AuditSessionQuery,
} from '../api/client';
import {
  auditRequestPrefix,
  auditSessionPrefix,
  auditSessionsPrefix,
  queryKeys,
} from '../lib/queryKeys';

export function useAuditSessions(query: AuditSessionQuery, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.auditSessions(query),
    queryFn: ({ signal }) => getAuditSessions(query, signal),
    enabled: options.enabled ?? true,
    retry: false,
  });
}

export function useAuditSession(sessionId: string | null, includeContent: boolean) {
  return useQuery({
    queryKey: queryKeys.auditSession(sessionId ?? '', includeContent),
    queryFn: ({ signal }) => {
      if (sessionId === null) {
        throw new Error('The audit session query started without a session.');
      }
      return getAuditSession(sessionId, includeContent, signal);
    },
    enabled: sessionId !== null,
    retry: false,
    placeholderData: keepPreviousData,
  });
}

export function useAuditRequest(requestId: string | null) {
  return useQuery({
    queryKey: queryKeys.auditRequest(requestId ?? ''),
    queryFn: ({ signal }) => {
      if (requestId === null) {
        throw new Error('The audit request query started without a request.');
      }
      return getAuditRequest(requestId, signal);
    },
    enabled: requestId !== null,
    retry: false,
  });
}

export function useAuditKeyOptions(tenantId: string | null) {
  return useQuery({
    queryKey: queryKeys.keyPage(tenantId, 100, 0),
    queryFn: ({ signal }) => {
      if (tenantId === null) {
        throw new Error('The audit key options query started without a tenant.');
      }
      return listKeys(signal, { tenantId, limit: 100, offset: 0 });
    },
    enabled: tenantId !== null,
    retry: false,
  });
}

export function useExportAudit() {
  return useMutation({
    mutationFn: (query: AuditExportQuery) => exportAuditRequests(query),
  });
}

export function useDeleteAudit() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (query: AuditDeleteQuery) => deleteAuditRequests(query),
    onSuccess: async (result) => {
      if (result.dry_run) return;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: auditSessionsPrefix }),
        queryClient.invalidateQueries({ queryKey: auditSessionPrefix }),
        queryClient.invalidateQueries({ queryKey: auditRequestPrefix }),
      ]);
    },
  });
}

export type AuditSessionsQuery = ReturnType<typeof useAuditSessions>;
export type AuditSessionQueryResult = ReturnType<typeof useAuditSession>;
export type AuditRequestQuery = ReturnType<typeof useAuditRequest>;
export type AuditKeyOptionsQuery = ReturnType<typeof useAuditKeyOptions>;
