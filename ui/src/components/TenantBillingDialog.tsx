import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import type { TenantBillingSummary, TenantLimitsPatch, TenantSummary } from '../api/client';
import { useTenantBilling } from '../hooks/useTenantBilling';
import { useUpdateTenantLimits } from '../hooks/useTenantMutations';
import { formatCost, formatCreatedDate, formatExactNumber } from '../lib/format';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface TenantBillingDialogProps {
  tenant: TenantSummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onSaved: (message: string) => void;
}

type FieldResult =
  | { status: 'unchanged' }
  | { status: 'set'; value: number | null }
  | { status: 'invalid'; message: string };

type BudgetResult =
  { status: 'unchanged' } | { status: 'set' } | { status: 'invalid'; message: string };

interface BillingFieldErrors {
  plan?: string;
  budget?: string;
}

const DECIMAL_PATTERN = /^\d+(\.\d+)?$/;

function fieldToInput(value: number | string | null): string {
  return value === null ? '' : String(value);
}

function parsePlanField(raw: string, original: string): FieldResult {
  const value = raw.trim();
  if (value === original) return { status: 'unchanged' };
  if (value === '') return { status: 'set', value: null };
  if (!/^\d+$/.test(value)) {
    return { status: 'invalid', message: 'Enter a whole number of 1 or more, or leave it blank.' };
  }

  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    return { status: 'invalid', message: 'Enter a whole number of 1 or more, or leave it blank.' };
  }

  return { status: 'set', value: parsed };
}

function parseBudgetField(raw: string, original: string): BudgetResult {
  const value = raw.trim();
  if (value === original) return { status: 'unchanged' };
  if (value === '') return { status: 'set' };
  if (!DECIMAL_PATTERN.test(value)) {
    return {
      status: 'invalid',
      message: 'Enter a non-negative amount, for example 25.00, or leave it blank.',
    };
  }

  return { status: 'set' };
}

function money(amount: string, currency: string): string {
  return `${currency} ${formatCost(amount)}`;
}

export function TenantBillingDialog({
  tenant,
  returnFocusRef,
  onClose,
  onSaved,
}: TenantBillingDialogProps) {
  const originalPlan = fieldToInput(tenant.plan_tokens);
  const originalBudget = fieldToInput(tenant.monthly_cost_budget);
  const [plan, setPlan] = useState(originalPlan);
  const [budget, setBudget] = useState(originalBudget);
  const [allowOverage, setAllowOverage] = useState(tenant.plan_allow_overage);
  const [fieldErrors, setFieldErrors] = useState<BillingFieldErrors>({});
  const titleId = useId();
  const planId = useId();
  const budgetId = useId();
  const planHintId = useId();
  const budgetHintId = useId();
  const overageLabelId = useId();
  const overageHintId = useId();
  const planErrorId = useId();
  const budgetErrorId = useId();
  const planRef = useRef<HTMLInputElement>(null);
  const billingQuery = useTenantBilling(tenant.id);
  const updateMutation = useUpdateTenantLimits();

  const pending = updateMutation.isPending;
  const planDirty = plan.trim() !== originalPlan;
  const budgetDirty = budget.trim() !== originalBudget;
  const overageDirty = allowOverage !== tenant.plan_allow_overage;
  const hasChanges = planDirty || budgetDirty || overageDirty;

  const clearing: string[] = [];
  if (planDirty && plan.trim() === '') clearing.push('plan tokens');
  if (budgetDirty && budget.trim() === '') clearing.push('monthly cost budget');

  const clearServerError = () => {
    if (updateMutation.isError) updateMutation.reset();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const planResult = parsePlanField(plan, originalPlan);
    const budgetResult = parseBudgetField(budget, originalBudget);
    const nextErrors: BillingFieldErrors = {};
    if (planResult.status === 'invalid') nextErrors.plan = planResult.message;
    if (budgetResult.status === 'invalid') nextErrors.budget = budgetResult.message;
    setFieldErrors(nextErrors);
    if (nextErrors.plan !== undefined || nextErrors.budget !== undefined) return;

    const patch: TenantLimitsPatch = {};
    if (planResult.status === 'set') patch.plan_tokens = planResult.value;
    if (budgetResult.status === 'set') {
      patch.monthly_cost_budget = budget.trim() === '' ? null : budget.trim();
    }
    if (overageDirty) patch.plan_allow_overage = allowOverage;
    if (Object.keys(patch).length === 0) return;

    updateMutation.mutate(
      { tenantId: tenant.id, patch },
      {
        onSuccess: (updated) => {
          onSaved(`Billing updated for ${updated.name}.`);
        },
      },
    );
  };

  const planDescribedBy =
    fieldErrors.plan === undefined ? planHintId : `${planHintId} ${planErrorId}`;
  const budgetDescribedBy =
    fieldErrors.budget === undefined ? budgetHintId : `${budgetHintId} ${budgetErrorId}`;

  return (
    <Modal
      labelledBy={titleId}
      onClose={onClose}
      closeDisabled={pending}
      initialFocusRef={planRef}
      returnFocusRef={returnFocusRef}
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Access
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Tenant billing
          </h3>
          <p className="mt-1 break-all font-mono text-[11px] text-ink-muted">{tenant.name}</p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={pending}
          aria-label="Close tenant billing dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <div className="px-5 py-4">
        {billingQuery.isPending ? (
          <BillingSkeleton />
        ) : billingQuery.isError ? (
          <RequestErrorPanel
            error={billingQuery.error}
            title="Could not load the billing summary"
            retryLabel="Retry loading the billing summary"
            onRetry={() => void billingQuery.refetch()}
          />
        ) : (
          <BillingSummary summary={billingQuery.data} headingId={`${titleId}-period`} />
        )}

        <p className="mt-3 text-[12px] leading-5 text-ink">
          Inside the plan: free. Over the plan: billed at list price.
        </p>
        <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">
          With overage off, requests fail with 429 plan_allowance_exhausted once the plan is used.
          Plans reset each UTC calendar month and do not roll over.
        </p>

        <form
          noValidate
          onSubmit={handleSubmit}
          className="mt-4 border-t border-line pt-3"
          aria-busy={pending}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor={planId} className="block text-[12px] font-medium text-ink">
                Plan tokens
              </label>
              <input
                ref={planRef}
                id={planId}
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                value={plan}
                onChange={(event) => {
                  setPlan(event.target.value);
                  setFieldErrors((current) => ({ ...current, plan: undefined }));
                  clearServerError();
                }}
                disabled={pending}
                placeholder="No plan"
                aria-invalid={fieldErrors.plan !== undefined}
                aria-describedby={planDescribedBy}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              />
              <p id={planHintId} className="mt-1 text-[11px] leading-4 text-ink-muted">
                Monthly token allowance. Blank means no plan.
              </p>
              {fieldErrors.plan !== undefined && (
                <p id={planErrorId} role="alert" className="mt-1 text-xs text-danger">
                  {fieldErrors.plan}
                </p>
              )}
            </div>

            <div>
              <label htmlFor={budgetId} className="block text-[12px] font-medium text-ink">
                Monthly cost budget
              </label>
              <input
                id={budgetId}
                type="text"
                inputMode="decimal"
                value={budget}
                onChange={(event) => {
                  setBudget(event.target.value);
                  setFieldErrors((current) => ({ ...current, budget: undefined }));
                  clearServerError();
                }}
                disabled={pending}
                autoComplete="off"
                placeholder="No budget"
                aria-invalid={fieldErrors.budget !== undefined}
                aria-describedby={budgetDescribedBy}
                className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
              />
              <p id={budgetHintId} className="mt-1 text-[11px] leading-4 text-ink-muted">
                Caps billed cost. At the cap, requests fail with 429 budget_exceeded.
              </p>
              {fieldErrors.budget !== undefined && (
                <p id={budgetErrorId} role="alert" className="mt-1 text-xs text-danger">
                  {fieldErrors.budget}
                </p>
              )}
            </div>
          </div>

          <div className="mt-3 border-t border-line pt-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p id={overageLabelId} className="text-[12px] font-medium text-ink">
                  Allow overage
                </p>
                <p id={overageHintId} className="mt-0.5 text-[11.5px] leading-4 text-ink-muted">
                  On: tokens beyond the plan are billed at list price. Off: the gateway rejects
                  requests with 429 plan_allowance_exhausted.
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={allowOverage}
                aria-labelledby={overageLabelId}
                aria-describedby={overageHintId}
                disabled={pending}
                onClick={() => {
                  setAllowOverage((current) => !current);
                  clearServerError();
                }}
                className="inline-flex shrink-0 items-center gap-2 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                <span
                  aria-hidden="true"
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                    allowOverage ? 'bg-accent' : 'bg-line-strong'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 size-4 rounded-full bg-white shadow-sm transition-transform ${
                      allowOverage ? 'translate-x-[1.125rem]' : 'translate-x-0.5'
                    }`}
                  />
                </span>
                <span className="w-6 font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-muted">
                  {allowOverage ? 'On' : 'Off'}
                </span>
              </button>
            </div>
          </div>

          {clearing.length > 0 && (
            <p className="mt-3 rounded border border-warn/30 bg-warn-soft px-2.5 py-1.5 text-[11.5px] text-warn">
              Will clear: {clearing.join(' and ')}.
            </p>
          )}

          {updateMutation.isError && updateMutation.error !== null && (
            <div className="mt-3">
              <RequestErrorPanel error={updateMutation.error} title="Could not update billing" />
            </div>
          )}

          <div className="mt-4 flex justify-end gap-2 border-t border-line pt-3">
            <Button variant="secondary" onClick={onClose} disabled={pending}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending || !hasChanges}>
              {pending ? 'Saving…' : 'Save billing'}
            </Button>
          </div>
        </form>
      </div>
    </Modal>
  );
}

function BillingSummary({
  summary,
  headingId,
}: {
  summary: TenantBillingSummary;
  headingId: string;
}) {
  const planLabel =
    summary.plan_tokens === null
      ? 'No plan'
      : `${formatExactNumber(summary.plan_tokens)} tokens / month`;
  const budgetLabel =
    summary.monthly_cost_budget === null
      ? 'No budget'
      : summary.budget_remaining === null
        ? money(summary.monthly_cost_budget, summary.currency)
        : money(summary.budget_remaining, summary.currency);

  const facts: Array<{ label: string; value: string; emphasis?: boolean }> = [
    { label: 'Plan', value: planLabel },
    { label: 'Requests', value: formatExactNumber(summary.requests) },
    { label: 'Used tokens', value: formatExactNumber(summary.used_tokens) },
    { label: 'Covered tokens', value: formatExactNumber(summary.covered_tokens) },
    { label: 'Billable tokens', value: formatExactNumber(summary.billable_tokens) },
    { label: 'List cost', value: money(summary.list_cost, summary.currency) },
    { label: 'Billed cost', value: money(summary.billed_cost, summary.currency), emphasis: true },
    { label: 'Budget remaining', value: budgetLabel },
  ];

  return (
    <section
      aria-labelledby={headingId}
      className="rounded-md border border-line bg-surface-sunken/40 px-3 py-2.5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4
          id={headingId}
          className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted"
        >
          Current period
        </h4>
        <p className="font-mono text-[10.5px] tabular-nums text-ink-muted">
          {formatCreatedDate(summary.period_start)} – {formatCreatedDate(summary.period_end)} ·{' '}
          {summary.currency}
        </p>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5">
        {facts.map((fact) => (
          <div key={fact.label}>
            <dt className="text-[10px] uppercase tracking-[0.06em] text-ink-muted">{fact.label}</dt>
            <dd
              className={`mt-0.5 font-mono text-[12px] tabular-nums ${
                fact.emphasis === true ? 'text-accent' : 'text-ink'
              }`}
            >
              {fact.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function BillingSkeleton() {
  return (
    <div>
      <span className="sr-only">Loading billing summary…</span>
      <div
        aria-hidden="true"
        className="rounded-md border border-line bg-surface-sunken/40 px-3 py-2.5"
      >
        <span className="block h-2.5 w-1/3 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none" />
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((cell) => (
            <span
              key={cell}
              className="h-2.5 w-3/4 animate-pulse rounded bg-surface-sunken motion-reduce:animate-none"
            />
          ))}
        </div>
      </div>
    </div>
  );
}
