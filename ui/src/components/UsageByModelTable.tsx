import type { UsageModelSummary } from '../api/client';
import { formatCost } from '../lib/format';
import { CompactNumber } from './CompactNumber';

interface UsageByModelTableProps {
  items: UsageModelSummary[];
}

function ModelName({ item }: { item: UsageModelSummary }) {
  return (
    <div className="min-w-0">
      <p className="break-words font-mono text-[12.5px] font-medium text-ink">{item.model_id}</p>
    </div>
  );
}

function ProviderCell({ provider }: { provider: string }) {
  return (
    <td className="py-2.5 pr-3 align-top font-mono text-[11px] break-words text-ink-muted last:pr-0">
      {provider.trim() === '' ? '—' : provider}
    </td>
  );
}

function NumericCell({ value, unit }: { value: number; unit: string }) {
  return (
    <td className="py-2.5 pr-3 text-right align-top font-mono text-[11.5px] tabular-nums last:pr-0">
      <CompactNumber value={value} unit={unit} />
    </td>
  );
}

function CostCell({ value }: { value: string }) {
  return (
    <td className="py-2.5 pr-3 text-right align-top font-mono text-[11.5px] tabular-nums last:pr-0">
      {formatCost(value)}
    </td>
  );
}

export function UsageByModelTable({ items }: UsageByModelTableProps) {
  if (items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
        <p className="text-[13px] text-ink-muted">No usage in this window.</p>
      </div>
    );
  }

  return (
    <>
      <div className="hidden md:block">
        <table className="w-full table-fixed border-collapse text-left text-[13px]">
          <caption className="sr-only">Usage by model</caption>
          <colgroup>
            <col className="w-[22%]" />
            <col className="w-[12%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col className="w-[7%]" />
            <col className="w-[9%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col className="w-[10%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-line">
              {[
                'Model',
                'Provider',
                'Requests',
                'Prompt',
                'Completion',
                'Cached',
                'Total',
                'Covered',
                'Billable',
                'Billed cost',
              ].map((label, index) => (
                <th
                  key={label}
                  scope="col"
                  className={`py-2 pr-3 font-mono text-[10px] font-medium uppercase tracking-[0.1em] text-ink-muted last:pr-0 ${
                    index < 2 ? 'text-left' : 'text-right'
                  }`}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((item) => (
              <tr
                key={`${item.provider}/${item.model_id}`}
                className="transition-colors hover:bg-surface-sunken/40"
              >
                <th scope="row" className="py-2.5 pr-3 align-top">
                  <ModelName item={item} />
                </th>
                <ProviderCell provider={item.provider} />
                <NumericCell value={item.requests} unit="requests" />
                <NumericCell value={item.prompt_tokens} unit="tokens" />
                <NumericCell value={item.completion_tokens} unit="tokens" />
                <NumericCell value={item.cached_tokens} unit="tokens" />
                <NumericCell value={item.total_tokens} unit="tokens" />
                <NumericCell value={item.covered_tokens} unit="tokens" />
                <NumericCell value={item.billable_tokens} unit="tokens" />
                <CostCell value={item.billed_cost} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul aria-label="Usage by model cards" className="divide-y divide-line md:hidden">
        {items.map((item) => (
          <li key={`${item.provider}/${item.model_id}`} className="py-3">
            <ModelName item={item} />
            <dl className="mt-2 grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
              <dt className="text-ink-muted">Provider</dt>
              <dd className="text-right font-mono text-[11.5px] break-words">
                {item.provider.trim() === '' ? '—' : item.provider}
              </dd>
              <dt className="text-ink-muted">Requests</dt>
              <dd className="text-right font-mono text-[11.5px]">
                <CompactNumber value={item.requests} unit="requests" />
              </dd>
              <dt className="text-ink-muted">Prompt</dt>
              <dd className="text-right font-mono text-[11.5px]">
                <CompactNumber value={item.prompt_tokens} unit="tokens" />
              </dd>
              <dt className="text-ink-muted">Completion</dt>
              <dd className="text-right font-mono text-[11.5px]">
                <CompactNumber value={item.completion_tokens} unit="tokens" />
              </dd>
              <dt className="text-ink-muted">Cached</dt>
              <dd className="text-right font-mono text-[11.5px]">
                <CompactNumber value={item.cached_tokens} unit="tokens" />
              </dd>
              <dt className="text-ink-muted">Total</dt>
              <dd className="text-right font-mono text-[11.5px]">
                <CompactNumber value={item.total_tokens} unit="tokens" />
              </dd>
              <dt className="text-ink-muted">Covered</dt>
              <dd className="text-right font-mono text-[11.5px]">
                <CompactNumber value={item.covered_tokens} unit="tokens" />
              </dd>
              <dt className="text-ink-muted">Billable</dt>
              <dd className="text-right font-mono text-[11.5px]">
                <CompactNumber value={item.billable_tokens} unit="tokens" />
              </dd>
              <dt className="text-ink-muted">Billed cost</dt>
              <dd className="text-right font-mono text-[11.5px]">{formatCost(item.billed_cost)}</dd>
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}
