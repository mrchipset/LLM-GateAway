import type { KeyUsageSummary } from '../api/client';
import { CompactNumber } from './CompactNumber';

interface UsageByKeyTableProps {
  items: KeyUsageSummary[];
  limit: number;
}

function keyLabel(item: KeyUsageSummary): string {
  const name = item.name?.trim();
  if (name !== undefined && name.length > 0) return name;

  const prefix = item.key_prefix?.trim();
  if (prefix !== undefined && prefix.length > 0) return prefix;

  return `${item.api_key_id.slice(0, 8)}…`;
}

function KeyName({ item }: { item: KeyUsageSummary }) {
  const name = item.name?.trim();
  const prefix = item.key_prefix?.trim();
  const showPrefix =
    name !== undefined && name.length > 0 && prefix !== undefined && prefix.length > 0;

  return (
    <div className="min-w-0">
      <p
        className="break-words font-mono text-[12.5px] font-medium text-ink"
        title={item.api_key_id}
      >
        {keyLabel(item)}
      </p>
      {showPrefix && (
        <p className="mt-0.5 font-mono text-[10.5px] break-all text-ink-muted">{prefix}</p>
      )}
    </div>
  );
}

function NumericCell({ value, unit }: { value: number; unit: string }) {
  return (
    <td className="py-2.5 pr-3 text-right align-top font-mono text-[11.5px] tabular-nums last:pr-0">
      <CompactNumber value={value} unit={unit} />
    </td>
  );
}

export function UsageByKeyTable({ items, limit }: UsageByKeyTableProps) {
  if (items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
        <h4 className="text-sm font-semibold text-ink">No usage in this range</h4>
        <p className="mt-1 text-[13px] text-ink-muted">
          No API key recorded requests for the selected tenant and window.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="hidden md:block">
        <table className="w-full table-fixed border-collapse text-left text-[13px]">
          <caption className="sr-only">Usage by API key</caption>
          <colgroup>
            <col className="w-[30%]" />
            <col className="w-[11%]" />
            <col className="w-[15%]" />
            <col className="w-[15%]" />
            <col className="w-[14%]" />
            <col className="w-[15%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-line">
              {['Key', 'Requests', 'Input', 'Output', 'Cached', 'Total'].map((label, index) => (
                <th
                  key={label}
                  scope="col"
                  className={`py-2 pr-3 font-mono text-[10px] font-medium uppercase tracking-[0.1em] text-ink-muted last:pr-0 ${
                    index === 0 ? 'text-left' : 'text-right'
                  }`}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((item) => (
              <tr key={item.api_key_id} className="transition-colors hover:bg-surface-sunken/40">
                <th scope="row" className="py-2.5 pr-3 align-top">
                  <KeyName item={item} />
                </th>
                <NumericCell value={item.requests} unit="requests" />
                <NumericCell value={item.prompt_tokens} unit="tokens" />
                <NumericCell value={item.completion_tokens} unit="tokens" />
                <NumericCell value={item.cached_tokens} unit="tokens" />
                <NumericCell value={item.total_tokens} unit="tokens" />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul aria-label="Usage by API key cards" className="divide-y divide-line md:hidden">
        {items.map((item) => (
          <li key={item.api_key_id} className="py-3">
            <KeyName item={item} />
            <dl className="mt-2 grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
              <dt className="text-ink-muted">Requests</dt>
              <dd className="text-right font-mono text-[11.5px]">
                <CompactNumber value={item.requests} unit="requests" />
              </dd>
              <dt className="text-ink-muted">Input</dt>
              <dd className="text-right font-mono text-[11.5px]">
                <CompactNumber value={item.prompt_tokens} unit="tokens" />
              </dd>
              <dt className="text-ink-muted">Output</dt>
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
            </dl>
          </li>
        ))}
      </ul>
      {items.length >= limit && (
        <p className="mt-2 text-[11px] text-ink-muted">
          Showing the top {limit} keys by total tokens.
        </p>
      )}
    </>
  );
}

export function UsageTableSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading usage by key…</span>
      <div aria-hidden="true" className="space-y-2">
        {[0, 1, 2, 3].map((row) => (
          <div
            key={row}
            className="grid grid-cols-[1.6fr_0.7fr_0.9fr_0.9fr_0.8fr_0.9fr] gap-4 rounded border border-line/70 px-3 py-3"
          >
            {[0, 1, 2, 3, 4, 5].map((cell) => (
              <span
                key={cell}
                className="h-3 w-4/5 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none"
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
