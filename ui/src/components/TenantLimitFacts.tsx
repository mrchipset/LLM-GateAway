import type { ReactNode } from 'react';

import type { TenantSummary } from '../api/client';
import { formatExactNumber } from '../lib/format';

interface TenantLimitFactsProps {
  tenant: Pick<TenantSummary, 'monthly_token_quota' | 'requests_per_minute'>;
}

export function TenantLimitFacts({ tenant }: TenantLimitFactsProps) {
  const quota = tenant.monthly_token_quota;
  const rate = tenant.requests_per_minute;

  if (quota === null && rate === null) {
    return <LimitFact>No limits</LimitFact>;
  }

  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {quota !== null ? (
        <LimitFact>{formatExactNumber(quota)} tokens/month</LimitFact>
      ) : (
        <LimitFact>No token limit</LimitFact>
      )}
      {rate !== null ? (
        <LimitFact>{formatExactNumber(rate)} req/min</LimitFact>
      ) : (
        <LimitFact>No rate limit</LimitFact>
      )}
    </span>
  );
}

function LimitFact({ children }: { children: ReactNode }) {
  return (
    <span className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-ink">
      {children}
    </span>
  );
}
