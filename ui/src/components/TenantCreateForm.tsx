import { useId, useState, type FormEvent } from 'react';

import type { CreateTenantInput } from '../api/client';
import { useCreateTenant } from '../hooks/useTenantMutations';
import { countErrorText, parseOptionalCount } from '../lib/limits';
import { TENANT_NAME_MAX_LENGTH, validateTenantName } from '../lib/tenants';
import { Button } from './Button';
import { RequestErrorPanel } from './RequestErrorPanel';

interface TenantCreateFormProps {
  onStart: () => void;
  onCreated: () => void;
}

interface LimitErrors {
  tokens?: string;
  concurrent?: string;
  retention?: string;
}

export function TenantCreateForm({ onStart, onCreated }: TenantCreateFormProps) {
  const [name, setName] = useState('');
  const [tokens, setTokens] = useState('');
  const [concurrent, setConcurrent] = useState('');
  const [retention, setRetention] = useState('');
  const [clientError, setClientError] = useState<string | null>(null);
  const [limitErrors, setLimitErrors] = useState<LimitErrors>({});
  const inputId = useId();
  const tokensId = useId();
  const concurrentId = useId();
  const retentionId = useId();
  const retentionHintId = useId();
  const errorId = useId();
  const tokensErrorId = useId();
  const concurrentErrorId = useId();
  const retentionErrorId = useId();
  const createMutation = useCreateTenant();

  const clearServerError = () => {
    if (createMutation.isError) createMutation.reset();
  };

  const handleNameChange = (value: string) => {
    setName(value);
    setClientError(null);
    clearServerError();
  };

  const handleLimitChange = (field: keyof LimitErrors, value: string) => {
    if (field === 'tokens') setTokens(value);
    if (field === 'concurrent') setConcurrent(value);
    if (field === 'retention') setRetention(value);
    setLimitErrors((current) => ({ ...current, [field]: undefined }));
    clearServerError();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onStart();

    const trimmed = name.trim();
    const nameError = validateTenantName(name);
    if (nameError !== undefined) {
      setClientError(nameError);
      return;
    }

    const tokensResult = parseOptionalCount(tokens, 1);
    const concurrentResult = parseOptionalCount(concurrent, 1);
    const retentionResult = parseOptionalCount(retention, 0);
    const nextErrors: LimitErrors = {};
    if (tokensResult.status === 'invalid') nextErrors.tokens = countErrorText(1);
    if (concurrentResult.status === 'invalid') nextErrors.concurrent = countErrorText(1);
    if (retentionResult.status === 'invalid') nextErrors.retention = countErrorText(0);
    setLimitErrors(nextErrors);
    if (Object.values(nextErrors).some((message) => message !== undefined)) return;

    setClientError(null);
    const input: CreateTenantInput = { name: trimmed };
    if (tokensResult.status === 'set') input.tokens_per_minute = tokensResult.value;
    if (concurrentResult.status === 'set') input.max_concurrent_requests = concurrentResult.value;
    if (retentionResult.status === 'set') input.audit_retention_days = retentionResult.value;

    createMutation.mutate(input, {
      onSuccess: () => {
        setName('');
        setTokens('');
        setConcurrent('');
        setRetention('');
        setClientError(null);
        setLimitErrors({});
        onCreated();
      },
    });
  };

  return (
    <section
      aria-labelledby={`${inputId}-heading`}
      className="rounded-md border border-line bg-surface-sunken/40 p-3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3
          id={`${inputId}-heading`}
          className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
        >
          Create tenant
        </h3>
        <p className="text-[10.5px] text-ink-muted">
          1–{TENANT_NAME_MAX_LENGTH} characters · limits are optional
        </p>
      </div>

      <form noValidate onSubmit={handleSubmit} className="mt-2">
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="min-w-0 flex-1">
            <label htmlFor={inputId} className="block text-[12px] font-medium text-ink">
              Tenant name
            </label>
            <input
              id={inputId}
              type="text"
              value={name}
              onChange={(event) => handleNameChange(event.target.value)}
              disabled={createMutation.isPending}
              autoComplete="off"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              aria-invalid={clientError !== null}
              aria-describedby={clientError !== null ? errorId : undefined}
              placeholder="e.g. Acme"
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            />
            {clientError !== null && (
              <p id={errorId} role="alert" className="mt-1 text-xs text-danger">
                {clientError}
              </p>
            )}
          </div>
          <Button
            type="submit"
            disabled={createMutation.isPending}
            className="shrink-0 sm:self-end"
          >
            {createMutation.isPending ? 'Creating…' : 'Create tenant'}
          </Button>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <div>
            <label htmlFor={tokensId} className="block text-[12px] font-medium text-ink">
              Tokens per minute
            </label>
            <input
              id={tokensId}
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              value={tokens}
              onChange={(event) => handleLimitChange('tokens', event.target.value)}
              disabled={createMutation.isPending}
              placeholder="No limit"
              aria-invalid={limitErrors.tokens !== undefined}
              aria-describedby={limitErrors.tokens === undefined ? undefined : tokensErrorId}
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            />
            {limitErrors.tokens !== undefined && (
              <p id={tokensErrorId} role="alert" className="mt-1 text-xs text-danger">
                {limitErrors.tokens}
              </p>
            )}
          </div>

          <div>
            <label htmlFor={concurrentId} className="block text-[12px] font-medium text-ink">
              Max concurrent requests
            </label>
            <input
              id={concurrentId}
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              value={concurrent}
              onChange={(event) => handleLimitChange('concurrent', event.target.value)}
              disabled={createMutation.isPending}
              placeholder="No limit"
              aria-invalid={limitErrors.concurrent !== undefined}
              aria-describedby={
                limitErrors.concurrent === undefined ? undefined : concurrentErrorId
              }
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            />
            {limitErrors.concurrent !== undefined && (
              <p id={concurrentErrorId} role="alert" className="mt-1 text-xs text-danger">
                {limitErrors.concurrent}
              </p>
            )}
          </div>

          <div>
            <label htmlFor={retentionId} className="block text-[12px] font-medium text-ink">
              Audit retention (days)
            </label>
            <input
              id={retentionId}
              type="number"
              min={0}
              step={1}
              inputMode="numeric"
              value={retention}
              onChange={(event) => handleLimitChange('retention', event.target.value)}
              disabled={createMutation.isPending}
              placeholder="Inherit default"
              aria-invalid={limitErrors.retention !== undefined}
              aria-describedby={
                limitErrors.retention === undefined
                  ? retentionHintId
                  : `${retentionHintId} ${retentionErrorId}`
              }
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink placeholder:font-sans placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            />
            <p id={retentionHintId} className="mt-1 text-[11px] leading-4 text-ink-muted">
              留空表示继承全局默认保留期；0 表示合规保留（永不自动删除）；正数表示保留天数。
            </p>
            {limitErrors.retention !== undefined && (
              <p id={retentionErrorId} role="alert" className="mt-1 text-xs text-danger">
                {limitErrors.retention}
              </p>
            )}
          </div>
        </div>
      </form>

      {createMutation.isError && createMutation.error !== null && (
        <div className="mt-3">
          <RequestErrorPanel error={createMutation.error} title="Could not create tenant" />
        </div>
      )}
    </section>
  );
}
