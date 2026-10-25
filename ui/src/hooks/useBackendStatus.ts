import { useQuery } from '@tanstack/react-query';

import { getHealth, getReadiness } from '../api/client';

const POLL_INTERVAL_MS = 15_000;

export interface FailedCheck {
  name: string;
  value: string;
}

export type BackendState =
  | { phase: 'checking' }
  | { phase: 'healthy' }
  | { phase: 'degraded'; failedChecks: FailedCheck[]; detail: 'checks' | 'unreachable' }
  | { phase: 'offline' };

export interface BackendStatus {
  state: BackendState;
  version: string | null;
  isRetrying: boolean;
  retry: () => Promise<void>;
}

export function useBackendStatus(): BackendStatus {
  const health = useQuery({
    queryKey: ['backend-health'],
    queryFn: ({ signal }) => getHealth(signal),
    retry: false,
    refetchInterval: POLL_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });

  const readiness = useQuery({
    queryKey: ['backend-readiness'],
    queryFn: ({ signal }) => getReadiness(signal),
    retry: false,
    refetchInterval: POLL_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });

  let state: BackendState;
  if (health.isError) {
    state = { phase: 'offline' };
  } else if (health.isPending || readiness.isPending) {
    state = { phase: 'checking' };
  } else if (readiness.isError) {
    state = { phase: 'degraded', failedChecks: [], detail: 'unreachable' };
  } else {
    const failedChecks = Object.entries(readiness.data.checks)
      .filter(([, value]) => value !== 'ok')
      .map(([name, value]) => ({ name, value }));
    state =
      readiness.data.status === 'ok' && failedChecks.length === 0
        ? { phase: 'healthy' }
        : { phase: 'degraded', failedChecks, detail: 'checks' };
  }

  return {
    state,
    version: health.data?.version ?? null,
    isRetrying: health.isFetching || readiness.isFetching,
    retry: async () => {
      await Promise.all([health.refetch(), readiness.refetch()]);
    },
  };
}
