import type { UsageSummaryResponse } from '../api/client';
import { CompactNumber } from './CompactNumber';

interface UsageStatsProps {
  summary: UsageSummaryResponse;
}

interface StatCell {
  key: string;
  label: string;
  value: number;
  unit: string;
  note?: string;
  emphasis?: boolean;
}

export function UsageStats({ summary }: UsageStatsProps) {
  const cells: StatCell[] = [
    { key: 'requests', label: 'Requests', value: summary.requests, unit: 'requests' },
    { key: 'input', label: 'Input tokens', value: summary.prompt_tokens, unit: 'tokens' },
    {
      key: 'output',
      label: 'Output tokens',
      value: summary.completion_tokens,
      unit: 'tokens',
    },
    {
      key: 'cached',
      label: 'Cached tokens',
      value: summary.cached_tokens,
      unit: 'tokens',
      note: 'subset of input',
    },
    {
      key: 'total',
      label: 'Total tokens',
      value: summary.total_tokens,
      unit: 'tokens',
      emphasis: true,
    },
  ];

  return (
    <dl
      aria-label="Usage totals"
      className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line sm:grid-cols-5"
    >
      {cells.map((cell) => (
        <div
          key={cell.key}
          className={`px-3 py-2.5 ${
            cell.emphasis ? 'col-span-2 bg-surface-sunken/70 sm:col-span-1' : 'bg-surface'
          }`}
        >
          <dt className="font-mono text-[10px] font-medium uppercase tracking-[0.1em] text-ink-muted">
            {cell.label}
          </dt>
          <dd
            className={`mt-1 font-mono text-[19px] font-medium leading-none tracking-[-0.02em] ${
              cell.emphasis ? 'text-accent' : 'text-ink'
            }`}
          >
            <CompactNumber value={cell.value} unit={cell.unit} />
          </dd>
          {cell.note !== undefined && (
            <p className="mt-1.5 text-[10px] leading-tight text-ink-muted">{cell.note}</p>
          )}
        </div>
      ))}
    </dl>
  );
}

export function UsageStatsSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading usage totals…</span>
      <div
        aria-hidden="true"
        className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line sm:grid-cols-5"
      >
        {[0, 1, 2, 3, 4].map((cell) => (
          <div
            key={cell}
            className={`bg-surface px-3 py-2.5 ${cell === 4 ? 'col-span-2 sm:col-span-1' : ''}`}
          >
            <span className="block h-2.5 w-3/4 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
            <span className="mt-2 block h-5 w-1/2 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
          </div>
        ))}
      </div>
    </div>
  );
}
