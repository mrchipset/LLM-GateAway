import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import type { CreateModelPriceInput, ModelPrice, ModelSummary } from '../api/client';
import { useCreateModelPrice } from '../hooks/useModelPriceMutations';
import { useModelPrices } from '../hooks/useModelPrices';
import { formatCreatedAt, formatExactNumber, trimDecimal } from '../lib/format';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface ModelPricingDialogProps {
  masterKey: string;
  model: ModelSummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
}

interface PriceFieldErrors {
  input?: string;
  cached?: string;
  output?: string;
  effective?: string;
}

const DECIMAL_PATTERN = /^\d+(\.\d+)?$/;

function decimalError(label: string): string {
  return `Enter a non-negative decimal for the ${label}, for example 0.28.`;
}

function sortNewestFirst(prices: ModelPrice[]): ModelPrice[] {
  const timestamp = (value: string) => {
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? 0 : parsed;
  };

  return [...prices].sort(
    (left, right) =>
      timestamp(right.effective_from) - timestamp(left.effective_from) ||
      timestamp(right.created_at) - timestamp(left.created_at),
  );
}

export function ModelPricingDialog({
  masterKey,
  model,
  returnFocusRef,
  onClose,
}: ModelPricingDialogProps) {
  const [input, setInput] = useState('');
  const [cached, setCached] = useState('');
  const [output, setOutput] = useState('');
  const [effectiveFrom, setEffectiveFrom] = useState('');
  const [fieldErrors, setFieldErrors] = useState<PriceFieldErrors>({});
  const [added, setAdded] = useState(false);
  const titleId = useId();
  const inputId = useId();
  const cachedId = useId();
  const outputId = useId();
  const effectiveId = useId();
  const hintId = useId();
  const cachedHintId = useId();
  const effectiveHintId = useId();
  const inputErrorId = useId();
  const cachedErrorId = useId();
  const outputErrorId = useId();
  const effectiveErrorId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const pricesQuery = useModelPrices(masterKey, model.id);
  const createMutation = useCreateModelPrice(masterKey);

  const pending = createMutation.isPending;
  const prices = pricesQuery.status === 'success' ? sortNewestFirst(pricesQuery.data.items) : [];

  const clearServerError = () => {
    setAdded(false);
    if (createMutation.isError) createMutation.reset();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmedInput = input.trim();
    const trimmedCached = cached.trim();
    const trimmedOutput = output.trim();
    const nextErrors: PriceFieldErrors = {};

    if (trimmedInput === '') nextErrors.input = 'Enter the input price per million tokens.';
    else if (!DECIMAL_PATTERN.test(trimmedInput)) nextErrors.input = decimalError('input price');

    if (trimmedCached !== '' && !DECIMAL_PATTERN.test(trimmedCached)) {
      nextErrors.cached = decimalError('cached input price');
    }

    if (trimmedOutput === '') nextErrors.output = 'Enter the output price per million tokens.';
    else if (!DECIMAL_PATTERN.test(trimmedOutput)) nextErrors.output = decimalError('output price');

    const payload: CreateModelPriceInput = {
      input_per_million: trimmedInput,
      output_per_million: trimmedOutput,
    };
    if (trimmedCached !== '') payload.cached_input_per_million = trimmedCached;

    if (effectiveFrom !== '') {
      const date = new Date(effectiveFrom);
      if (Number.isNaN(date.getTime())) {
        nextErrors.effective = 'Enter a valid date and time.';
      } else {
        payload.effective_from = date.toISOString();
      }
    }

    setFieldErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    createMutation.mutate(
      { modelId: model.id, input: payload },
      {
        onSuccess: () => {
          setInput('');
          setCached('');
          setOutput('');
          setEffectiveFrom('');
          setAdded(true);
        },
      },
    );
  };

  const inputDescribedBy = fieldErrors.input === undefined ? hintId : `${hintId} ${inputErrorId}`;
  const cachedDescribedBy =
    fieldErrors.cached === undefined ? cachedHintId : `${cachedHintId} ${cachedErrorId}`;
  const outputDescribedBy =
    fieldErrors.output === undefined ? hintId : `${hintId} ${outputErrorId}`;
  const effectiveDescribedBy =
    fieldErrors.effective === undefined
      ? effectiveHintId
      : `${effectiveHintId} ${effectiveErrorId}`;

  return (
    <Modal
      labelledBy={titleId}
      onClose={onClose}
      closeDisabled={pending}
      initialFocusRef={inputRef}
      returnFocusRef={returnFocusRef}
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Registry
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Model pricing
          </h3>
          <p className="mt-1 break-all font-mono text-[11px] text-ink-muted">{model.id}</p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={pending}
          aria-label="Close model pricing dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <div className="px-5 py-4">
        <p className="text-[11.5px] leading-5 text-ink-muted">
          Prices are per million tokens. A new version applies from its effective date; older
          versions stay unchanged.
        </p>

        <div className="mt-4 flex items-baseline justify-between gap-2">
          <h4 className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
            Price versions
          </h4>
          {pricesQuery.status === 'success' && prices.length > 0 && (
            <span className="font-mono text-[10px] tabular-nums text-ink-muted">
              {pricesQuery.data.total > prices.length
                ? `Showing ${formatExactNumber(prices.length)} of ${formatExactNumber(pricesQuery.data.total)}`
                : pricesQuery.data.total === 1
                  ? '1 version'
                  : `${formatExactNumber(pricesQuery.data.total)} versions`}{' '}
              · newest first
            </span>
          )}
        </div>
        <div className="mt-1.5">
          {pricesQuery.isPending ? (
            <PriceSkeleton />
          ) : pricesQuery.isError ? (
            <RequestErrorPanel
              error={pricesQuery.error}
              title="Could not load price versions"
              retryLabel="Retry loading price versions"
              onRetry={() => void pricesQuery.refetch()}
            />
          ) : prices.length === 0 ? (
            <p className="rounded-md border border-dashed border-line-strong px-3 py-4 text-[12px] text-ink-muted">
              No price versions yet. Tenants with a plan or budget need a price on every model they
              use; without one, requests fail with 503 model_price_missing.
            </p>
          ) : (
            <ul
              aria-label="Price versions"
              className="divide-y divide-line overflow-hidden rounded-md border border-line"
            >
              {prices.map((price) => (
                <li key={price.id} className="px-3 py-2.5">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
                    <time
                      dateTime={price.effective_from}
                      className="font-mono text-[11.5px] tabular-nums text-ink"
                    >
                      {formatCreatedAt(price.effective_from)}
                    </time>
                    <span className="rounded border border-line bg-surface-sunken px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-ink-muted">
                      {price.currency}
                    </span>
                  </div>
                  <dl className="mt-1.5 grid grid-cols-3 gap-2">
                    <PriceCell label="Input / 1M" value={price.input_per_million} />
                    <PriceCell
                      label="Cached / 1M"
                      value={price.cached_input_per_million}
                      fallback="Same as input"
                    />
                    <PriceCell label="Output / 1M" value={price.output_per_million} />
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </div>

        <form
          noValidate
          onSubmit={handleSubmit}
          className="mt-4 border-t border-line pt-3"
          aria-busy={pending}
        >
          <h4 className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
            Add price version
          </h4>
          <p id={hintId} className="mt-1 text-[11.5px] leading-5 text-ink-muted">
            Amounts are per million tokens. Existing versions are never rewritten.
          </p>

          <div className="mt-2 grid gap-3 sm:grid-cols-3">
            <div>
              <label htmlFor={inputId} className="block text-[12px] font-medium text-ink">
                Input per million tokens
              </label>
              <input
                ref={inputRef}
                id={inputId}
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                value={input}
                onChange={(event) => {
                  setInput(event.target.value);
                  setFieldErrors((current) => ({ ...current, input: undefined }));
                  clearServerError();
                }}
                disabled={pending}
                placeholder="0.28"
                aria-invalid={fieldErrors.input !== undefined}
                aria-describedby={inputDescribedBy}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              />
              {fieldErrors.input !== undefined && (
                <p id={inputErrorId} role="alert" className="mt-1 text-xs text-danger">
                  {fieldErrors.input}
                </p>
              )}
            </div>

            <div>
              <label htmlFor={cachedId} className="block text-[12px] font-medium text-ink">
                Cached input per million tokens
              </label>
              <input
                id={cachedId}
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                value={cached}
                onChange={(event) => {
                  setCached(event.target.value);
                  setFieldErrors((current) => ({ ...current, cached: undefined }));
                  clearServerError();
                }}
                disabled={pending}
                placeholder="Optional"
                aria-invalid={fieldErrors.cached !== undefined}
                aria-describedby={cachedDescribedBy}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              />
              <p id={cachedHintId} className="mt-1 text-[11px] leading-4 text-ink-muted">
                Optional. Blank uses the input price.
              </p>
              {fieldErrors.cached !== undefined && (
                <p id={cachedErrorId} role="alert" className="mt-1 text-xs text-danger">
                  {fieldErrors.cached}
                </p>
              )}
            </div>

            <div>
              <label htmlFor={outputId} className="block text-[12px] font-medium text-ink">
                Output per million tokens
              </label>
              <input
                id={outputId}
                type="number"
                min={0}
                step="any"
                inputMode="decimal"
                value={output}
                onChange={(event) => {
                  setOutput(event.target.value);
                  setFieldErrors((current) => ({ ...current, output: undefined }));
                  clearServerError();
                }}
                disabled={pending}
                placeholder="0.42"
                aria-invalid={fieldErrors.output !== undefined}
                aria-describedby={outputDescribedBy}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              />
              {fieldErrors.output !== undefined && (
                <p id={outputErrorId} role="alert" className="mt-1 text-xs text-danger">
                  {fieldErrors.output}
                </p>
              )}
            </div>
          </div>

          <div className="mt-3">
            <label htmlFor={effectiveId} className="block text-[12px] font-medium text-ink">
              Effective from
            </label>
            <input
              id={effectiveId}
              type="datetime-local"
              value={effectiveFrom}
              onChange={(event) => {
                setEffectiveFrom(event.target.value);
                setFieldErrors((current) => ({ ...current, effective: undefined }));
                clearServerError();
              }}
              disabled={pending}
              aria-invalid={fieldErrors.effective !== undefined}
              aria-describedby={effectiveDescribedBy}
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted sm:max-w-xs"
            />
            <p id={effectiveHintId} className="mt-1 text-[11px] leading-4 text-ink-muted">
              Optional. Defaults to now. Your local time; stored and displayed in UTC.
            </p>
            {fieldErrors.effective !== undefined && (
              <p id={effectiveErrorId} role="alert" className="mt-1 text-xs text-danger">
                {fieldErrors.effective}
              </p>
            )}
          </div>

          {added && (
            <p
              role="status"
              className="mt-3 rounded border border-ok/25 bg-ok-soft px-2.5 py-1.5 text-[11.5px] text-ok"
            >
              Price version added.
            </p>
          )}

          {createMutation.isError && createMutation.error !== null && (
            <div className="mt-3">
              <RequestErrorPanel error={createMutation.error} title="Could not add price version" />
            </div>
          )}

          <div className="mt-3 flex justify-end">
            <Button type="submit" disabled={pending}>
              {pending ? 'Adding…' : 'Add price version'}
            </Button>
          </div>
        </form>
      </div>
    </Modal>
  );
}

function PriceCell({
  label,
  value,
  fallback,
}: {
  label: string;
  value: string | null;
  fallback?: string;
}) {
  return (
    <div>
      <dt className="font-mono text-[9.5px] font-medium uppercase tracking-[0.1em] text-ink-muted">
        {label}
      </dt>
      <dd className="mt-0.5 font-mono text-[12px] tabular-nums text-ink">
        {value === null ? (
          <span className="font-sans text-[11.5px] text-ink-muted">{fallback ?? '—'}</span>
        ) : (
          trimDecimal(value)
        )}
      </dd>
    </div>
  );
}

function PriceSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading price versions…</span>
      <div aria-hidden="true" className="space-y-2">
        {[0, 1].map((row) => (
          <div key={row} className="rounded border border-line/70 px-3 py-2.5">
            <span className="block h-2.5 w-1/2 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
            <div className="mt-2 grid grid-cols-3 gap-2">
              {[0, 1, 2].map((cell) => (
                <span
                  key={cell}
                  className="h-2.5 w-3/4 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none"
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
