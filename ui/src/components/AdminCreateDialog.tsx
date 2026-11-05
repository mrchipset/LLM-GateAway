import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import type { AdminRole, AdminSummary } from '../api/client';
import { useCreateAdmin } from '../hooks/useAdmins';
import {
  ADMIN_ROLE_HELP,
  ADMIN_ROLE_OPTIONS,
  hasDraftErrors,
  validateAdminDraft,
  type AdminDraftErrors,
} from '../lib/admins';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface AdminCreateDialogProps {
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onCreated: (admin: AdminSummary) => void;
}

const FIELD_CLASS =
  'mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15';

export function AdminCreateDialog({ returnFocusRef, onClose, onCreated }: AdminCreateDialogProps) {
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState<AdminRole>('operator');
  const [password, setPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<AdminDraftErrors>({});
  const titleId = useId();
  const usernameId = useId();
  const usernameHintId = useId();
  const usernameErrorId = useId();
  const displayNameId = useId();
  const displayNameErrorId = useId();
  const roleId = useId();
  const roleHelpId = useId();
  const passwordId = useId();
  const passwordHintId = useId();
  const passwordErrorId = useId();
  const usernameRef = useRef<HTMLInputElement>(null);
  const createMutation = useCreateAdmin();
  const pending = createMutation.isPending;

  const clearServerError = () => {
    if (createMutation.isError) createMutation.reset();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextErrors = validateAdminDraft({ username, displayName, password });
    setFieldErrors(nextErrors);
    if (hasDraftErrors(nextErrors)) return;

    createMutation.mutate(
      {
        username: username.trim(),
        display_name: displayName.trim(),
        role,
        password,
      },
      {
        onSuccess: (admin) => {
          onCreated(admin);
        },
      },
    );
  };

  const usernameDescribedBy =
    fieldErrors.username === undefined ? usernameHintId : `${usernameHintId} ${usernameErrorId}`;
  const passwordDescribedBy =
    fieldErrors.password === undefined ? passwordHintId : `${passwordHintId} ${passwordErrorId}`;

  return (
    <Modal
      labelledBy={titleId}
      initialFocusRef={usernameRef}
      returnFocusRef={returnFocusRef}
      onClose={onClose}
      closeDisabled={pending}
    >
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Identity
          </p>
          <h2 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Create admin
          </h2>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={pending}
          aria-label="Close create admin dialog"
          className="px-1.5 py-1"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <form onSubmit={handleSubmit} className="p-5" noValidate aria-busy={pending}>
        <div>
          <label htmlFor={usernameId} className="block text-[13px] font-medium text-ink">
            Username
          </label>
          <input
            ref={usernameRef}
            id={usernameId}
            type="text"
            value={username}
            onChange={(event) => {
              setUsername(event.target.value);
              clearServerError();
            }}
            disabled={pending}
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            aria-invalid={fieldErrors.username !== undefined}
            aria-describedby={usernameDescribedBy}
            placeholder="jane.doe"
            className={FIELD_CLASS}
          />
          <p id={usernameHintId} className="mt-1 text-[11.5px] text-ink-muted">
            3–64 characters: lowercase letters, numbers, and . _ -
          </p>
          {fieldErrors.username !== undefined && (
            <p id={usernameErrorId} role="alert" className="mt-1 text-[11.5px] text-danger">
              {fieldErrors.username}
            </p>
          )}
        </div>

        <div className="mt-4">
          <label htmlFor={displayNameId} className="block text-[13px] font-medium text-ink">
            Display name
          </label>
          <input
            id={displayNameId}
            type="text"
            value={displayName}
            onChange={(event) => {
              setDisplayName(event.target.value);
              clearServerError();
            }}
            disabled={pending}
            autoComplete="off"
            aria-invalid={fieldErrors.displayName !== undefined}
            aria-describedby={
              fieldErrors.displayName === undefined ? undefined : displayNameErrorId
            }
            placeholder="Jane Doe"
            className={FIELD_CLASS}
          />
          {fieldErrors.displayName !== undefined && (
            <p id={displayNameErrorId} role="alert" className="mt-1 text-[11.5px] text-danger">
              {fieldErrors.displayName}
            </p>
          )}
        </div>

        <div className="mt-4">
          <label htmlFor={roleId} className="block text-[13px] font-medium text-ink">
            Role
          </label>
          <select
            id={roleId}
            value={role}
            onChange={(event) => {
              setRole(event.target.value as AdminRole);
              clearServerError();
            }}
            disabled={pending}
            aria-describedby={roleHelpId}
            className={FIELD_CLASS}
          >
            {ADMIN_ROLE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <p id={roleHelpId} className="mt-1 text-[11.5px] text-ink-muted">
            {ADMIN_ROLE_HELP[role]}
          </p>
        </div>

        <div className="mt-4">
          <label htmlFor={passwordId} className="block text-[13px] font-medium text-ink">
            Password
          </label>
          <input
            id={passwordId}
            type="password"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              clearServerError();
            }}
            disabled={pending}
            autoComplete="new-password"
            aria-invalid={fieldErrors.password !== undefined}
            aria-describedby={passwordDescribedBy}
            className={FIELD_CLASS}
          />
          <p id={passwordHintId} className="mt-1 text-[11.5px] text-ink-muted">
            At least 12 characters. It is never shown again after saving.
          </p>
          {fieldErrors.password !== undefined && (
            <p id={passwordErrorId} role="alert" className="mt-1 text-[11.5px] text-danger">
              {fieldErrors.password}
            </p>
          )}
        </div>

        {createMutation.isError && (
          <div className="mt-4">
            <RequestErrorPanel error={createMutation.error} title="Could not create admin" />
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2 border-t border-line pt-4">
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" disabled={pending}>
            {pending ? 'Creating…' : 'Create admin'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
