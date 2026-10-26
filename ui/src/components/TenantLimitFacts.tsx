import type { ReactNode } from 'react';

import type { TenantSummary } from '../api/client';
import { formatExactNumber } from '../lib/format';

type TenantLimitFactsVariant = 'chips' | 'compact';

interface TenantLimitFactsProps {
  tenant: Pick<TenantSummary, 'monthly_token_quota' | 'requests_per_minute'>;
  variant?: TenantLimitFactsVariant;
}

export function TenantLimitFacts({ tenant, variant = 'chips' }: TenantLimitFactsProps) {
  const quota = tenant.monthly_token_quota;
  const rate = tenant.requests_per_minute;

  if (variant === 'compact') return <CompactLimitFacts quota={quota} rate={rate} />;

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

function CompactLimitFacts({ quota, rate }: { quota: number | null; rate: number | null }) {
  if (quota === null && rate === null) {
    return <span className="text-[11px] text-ink-muted">No limits</span>;
  }

  return (
    <dl className="grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-1.5 gap-y-0.5 text-[11px]">
      <dt className="text-ink-muted">Tokens</dt>
      <dd
        className="break-words font-mono text-[10.5px] tabular-nums text-ink"
        title={limitTitle(quota, 'tokens per month', 'No token limit')}
      >
        <span aria-hidden="true">
          {quota === null ? 'No limit' : `${formatExactNumber(quota)}/mo`}
        </span>
        <span className="sr-only">{limitTitle(quota, 'tokens per month', 'No token limit')}</span>
      </dd>
      <dt className="text-ink-muted">Rate</dt>
      <dd
        className="break-words font-mono text-[10.5px] tabular-nums text-ink"
        title={limitTitle(rate, 'requests per minute', 'No rate limit')}
      >
        <span aria-hidden="true">
          {rate === null ? 'No limit' : `${formatExactNumber(rate)}/min`}
        </span>
        <span className="sr-only">{limitTitle(rate, 'requests per minute', 'No rate limit')}</span>
      </dd>
    </dl>
  );
}

function limitTitle(value: number | null, unit: string, noLimitLabel: string): string {
  return value === null ? noLimitLabel : `${formatExactNumber(value)} ${unit}`;
}

function LimitFact({ children }: { children: ReactNode }) {
  return (
    <span className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-ink">
      {children}
    </span>
  );
}
