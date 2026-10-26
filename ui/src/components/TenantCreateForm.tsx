import { useId, useState, type FormEvent } from 'react';

import { useCreateTenant } from '../hooks/useTenantMutations';
import { Button } from './Button';
import { RequestErrorPanel } from './RequestErrorPanel';

const NAME_MAX_LENGTH = 100;

interface TenantCreateFormProps {
  masterKey: string;
  onStart: () => void;
  onCreated: () => void;
}

export function TenantCreateForm({ masterKey, onStart, onCreated }: TenantCreateFormProps) {
  const [name, setName] = useState('');
  const [clientError, setClientError] = useState<string | null>(null);
  const inputId = useId();
  const errorId = useId();
  const createMutation = useCreateTenant(masterKey);

  const handleNameChange = (value: string) => {
    setName(value);
    setClientError(null);
    if (createMutation.isError) createMutation.reset();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onStart();

    const trimmed = name.trim();
    if (trimmed.length === 0) {
      setClientError('Enter a tenant name.');
      return;
    }
    if (trimmed.length > NAME_MAX_LENGTH) {
      setClientError(`Use ${NAME_MAX_LENGTH} characters or fewer.`);
      return;
    }

    setClientError(null);
    createMutation.mutate(
      { name: trimmed },
      {
        onSuccess: () => {
          setName('');
          setClientError(null);
          onCreated();
        },
      },
    );
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
          1–{NAME_MAX_LENGTH} characters · limits can be set after creation
        </p>
      </div>

      <form noValidate onSubmit={handleSubmit} className="mt-2 flex flex-col gap-2 sm:flex-row">
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
        <Button type="submit" disabled={createMutation.isPending} className="shrink-0 sm:self-end">
          {createMutation.isPending ? 'Creating…' : 'Create tenant'}
        </Button>
      </form>

      {createMutation.isError && createMutation.error !== null && (
        <div className="mt-3">
          <RequestErrorPanel error={createMutation.error} title="Could not create tenant" />
        </div>
      )}
    </section>
  );
}
