import type { ReactNode } from 'react';

import type { TenantSummary } from '../api/client';
import { formatExactNumber } from '../lib/format';

type TenantLimitFactsVariant = 'chips' | 'compact';

type TenantLimitFields = Pick<
  TenantSummary,
  | 'monthly_token_quota'
  | 'requests_per_minute'
  | 'tokens_per_minute'
  | 'max_concurrent_requests'
  | 'audit_retention_days'
>;

interface TenantLimitFactsProps {
  tenant: TenantLimitFields;
  variant?: TenantLimitFactsVariant;
}

function retentionLabel(value: number | null | undefined): string | null {
  if (value === undefined) return null;
  if (value === null) return 'Inherit default';
  if (value === 0) return 'Legal hold';
  return `${formatExactNumber(value)} days`;
}

export function TenantLimitFacts({ tenant, variant = 'chips' }: TenantLimitFactsProps) {
  const quota = tenant.monthly_token_quota;
  const rate = tenant.requests_per_minute;
  const tokens = tenant.tokens_per_minute ?? null;
  const concurrent = tenant.max_concurrent_requests ?? null;
  const retention = retentionLabel(tenant.audit_retention_days);

  if (variant === 'compact') {
    return (
      <CompactLimitFacts
        quota={quota}
        rate={rate}
        tokens={tokens}
        concurrent={concurrent}
        retention={retention}
      />
    );
  }

  if (
    quota === null &&
    rate === null &&
    tokens === null &&
    concurrent === null &&
    retention === null
  ) {
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
      {tokens !== null && <LimitFact>{formatExactNumber(tokens)} tokens/min</LimitFact>}
      {concurrent !== null && <LimitFact>{formatExactNumber(concurrent)} concurrent</LimitFact>}
      {retention !== null && <LimitFact>Retention: {retention}</LimitFact>}
    </span>
  );
}

function CompactLimitFacts({
  quota,
  rate,
  tokens,
  concurrent,
  retention,
}: {
  quota: number | null;
  rate: number | null;
  tokens: number | null;
  concurrent: number | null;
  retention: string | null;
}) {
  const isEmpty =
    quota === null && rate === null && tokens === null && concurrent === null && retention === null;
  if (isEmpty) {
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
      {tokens !== null && (
        <>
          <dt className="text-ink-muted">Tok/min</dt>
          <dd
            className="break-words font-mono text-[10.5px] tabular-nums text-ink"
            title={limitTitle(tokens, 'tokens per minute', 'No token rate limit')}
          >
            <span aria-hidden="true">{formatExactNumber(tokens)}/min</span>
            <span className="sr-only">
              {limitTitle(tokens, 'tokens per minute', 'No token rate limit')}
            </span>
          </dd>
        </>
      )}
      {concurrent !== null && (
        <>
          <dt className="text-ink-muted">Conc.</dt>
          <dd
            className="break-words font-mono text-[10.5px] tabular-nums text-ink"
            title={`${formatExactNumber(concurrent)} concurrent requests`}
          >
            <span aria-hidden="true">{formatExactNumber(concurrent)}</span>
            <span className="sr-only">{formatExactNumber(concurrent)} concurrent requests</span>
          </dd>
        </>
      )}
      {retention !== null && (
        <>
          <dt className="text-ink-muted">Retain</dt>
          <dd
            className="break-words font-mono text-[10.5px] tabular-nums text-ink"
            title={`Audit retention: ${retention}`}
          >
            <span aria-hidden="true">
              {retention === 'Legal hold'
                ? 'Hold'
                : retention === 'Inherit default'
                  ? 'Inherit'
                  : retention.replace(' days', 'd')}
            </span>
            <span className="sr-only">Audit retention: {retention}</span>
          </dd>
        </>
      )}
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
