import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import type { CreateApiKeyInput, CreatedApiKey, TenantSummary } from '../api/client';
import type { useCreateKey } from '../hooks/useKeyMutations';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

type CreateKeyMutation = ReturnType<typeof useCreateKey>;

const NAME_MAX_LENGTH = 100;

interface FieldErrors {
  tenant?: string;
  name?: string;
  expiry?: string;
}

interface KeyCreateDialogProps {
  tenants: TenantSummary[];
  initialTenantId: string | null;
  createMutation: CreateKeyMutation;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onCreated: (created: CreatedApiKey) => void;
}

export function KeyCreateDialog({
  tenants,
  initialTenantId,
  createMutation,
  returnFocusRef,
  onClose,
  onCreated,
}: KeyCreateDialogProps) {
  const [tenantId, setTenantId] = useState(initialTenantId ?? '');
  const [name, setName] = useState('');
  const [expiry, setExpiry] = useState('');
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const titleId = useId();
  const tenantIdInput = useId();
  const nameId = useId();
  const expiryId = useId();
  const expiryHintId = useId();
  const tenantErrorId = useId();
  const nameErrorId = useId();
  const expiryErrorId = useId();
  const nameRef = useRef<HTMLInputElement>(null);

  const pending = createMutation.isPending;

  const clearServerError = () => {
    if (createMutation.isError) createMutation.reset();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmedName = name.trim();
    const nextErrors: FieldErrors = {};

    if (tenantId === '') nextErrors.tenant = 'Select a tenant.';

    if (trimmedName.length === 0) {
      nextErrors.name = 'Enter a key name.';
    } else if (trimmedName.length > NAME_MAX_LENGTH) {
      nextErrors.name = `Use ${NAME_MAX_LENGTH} characters or fewer.`;
    }

    let expiresAt: string | undefined;
    if (expiry.trim() !== '') {
      const parsed = new Date(expiry);
      if (Number.isNaN(parsed.getTime())) {
        nextErrors.expiry = 'Enter a valid expiry time.';
      } else if (parsed.getTime() <= Date.now()) {
        nextErrors.expiry = 'Enter an expiry in the future.';
      } else {
        expiresAt = parsed.toISOString();
      }
    }

    setFieldErrors(nextErrors);
    if (
      nextErrors.tenant !== undefined ||
      nextErrors.name !== undefined ||
      nextErrors.expiry !== undefined
    ) {
      return;
    }

    const input: CreateApiKeyInput = { name: trimmedName, tenant_id: tenantId };
    if (expiresAt !== undefined) input.expires_at = expiresAt;

    createMutation.mutate(input, {
      onSuccess: (created) => {
        onCreated(created);
      },
    });
  };

  const tenantDescribedBy = fieldErrors.tenant === undefined ? undefined : tenantErrorId;
  const nameDescribedBy = fieldErrors.name === undefined ? undefined : nameErrorId;
  const expiryDescribedBy =
    fieldErrors.expiry === undefined ? expiryHintId : `${expiryHintId} ${expiryErrorId}`;

  return (
    <Modal
      labelledBy={titleId}
      onClose={onClose}
      closeDisabled={pending}
      initialFocusRef={nameRef}
      returnFocusRef={returnFocusRef}
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Access
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Create API key
          </h3>
          <p className="mt-1 text-[11.5px] text-ink-muted">
            The plaintext key is shown once after creation.
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={pending}
          aria-label="Close create key dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <form noValidate onSubmit={handleSubmit} className="px-5 py-4" aria-busy={pending}>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor={tenantIdInput} className="block text-[12px] font-medium text-ink">
              Tenant
            </label>
            <select
              id={tenantIdInput}
              value={tenantId}
              onChange={(event) => {
                setTenantId(event.target.value);
                setFieldErrors((current) => ({ ...current, tenant: undefined }));
                clearServerError();
              }}
              disabled={pending}
              aria-invalid={fieldErrors.tenant !== undefined}
              aria-describedby={tenantDescribedBy}
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            >
              <option value="" disabled>
                Select a tenant
              </option>
              {tenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.name}
                </option>
              ))}
            </select>
            {fieldErrors.tenant !== undefined && (
              <p id={tenantErrorId} role="alert" className="mt-1 text-xs text-danger">
                {fieldErrors.tenant}
              </p>
            )}
          </div>

          <div>
            <label htmlFor={nameId} className="block text-[12px] font-medium text-ink">
              Key name
            </label>
            <input
              ref={nameRef}
              id={nameId}
              type="text"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setFieldErrors((current) => ({ ...current, name: undefined }));
                clearServerError();
              }}
              disabled={pending}
              autoComplete="off"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              aria-invalid={fieldErrors.name !== undefined}
              aria-describedby={nameDescribedBy}
              placeholder="e.g. Production"
              className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted"
            />
            {fieldErrors.name !== undefined && (
              <p id={nameErrorId} role="alert" className="mt-1 text-xs text-danger">
                {fieldErrors.name}
              </p>
            )}
          </div>
        </div>

        <div className="mt-3">
          <label htmlFor={expiryId} className="block text-[12px] font-medium text-ink">
            Expires at (optional)
          </label>
          <input
            id={expiryId}
            type="datetime-local"
            value={expiry}
            onChange={(event) => {
              setExpiry(event.target.value);
              setFieldErrors((current) => ({ ...current, expiry: undefined }));
              clearServerError();
            }}
            disabled={pending}
            aria-invalid={fieldErrors.expiry !== undefined}
            aria-describedby={expiryDescribedBy}
            className="mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] tabular-nums text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted sm:max-w-xs"
          />
          <p id={expiryHintId} className="mt-1 text-[11px] text-ink-muted">
            Uses this browser&apos;s local time and is sent as UTC. Leave blank for no expiry.
          </p>
          {fieldErrors.expiry !== undefined && (
            <p id={expiryErrorId} role="alert" className="mt-1 text-xs text-danger">
              {fieldErrors.expiry}
            </p>
          )}
        </div>

        {createMutation.isError && createMutation.error !== null && (
          <div className="mt-3">
            <RequestErrorPanel error={createMutation.error} title="Could not create API key" />
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2 border-t border-line pt-3">
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" disabled={pending}>
            {pending ? 'Creating…' : 'Create key'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
