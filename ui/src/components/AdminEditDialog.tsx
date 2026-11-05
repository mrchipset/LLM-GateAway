import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import type { AdminRole, AdminSummary, UpdateAdminInput } from '../api/client';
import { useUpdateAdmin } from '../hooks/useAdmins';
import { ADMIN_DISPLAY_NAME_MAX_LENGTH, ADMIN_ROLE_HELP, ADMIN_ROLE_OPTIONS } from '../lib/admins';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface AdminEditDialogProps {
  admin: AdminSummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onSaved: (admin: AdminSummary) => void;
}

const FIELD_CLASS =
  'mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:cursor-not-allowed disabled:bg-surface-sunken disabled:text-ink-muted';

export function AdminEditDialog({ admin, returnFocusRef, onClose, onSaved }: AdminEditDialogProps) {
  const [displayName, setDisplayName] = useState(admin.display_name);
  const [role, setRole] = useState<AdminRole>(admin.role);
  const [active, setActive] = useState(admin.active);
  const [deactivateConfirmed, setDeactivateConfirmed] = useState(false);
  const [displayNameError, setDisplayNameError] = useState<string | null>(null);
  const titleId = useId();
  const displayNameId = useId();
  const displayNameErrorId = useId();
  const roleId = useId();
  const roleHelpId = useId();
  const activeLabelId = useId();
  const activeHintId = useId();
  const confirmId = useId();
  const displayNameRef = useRef<HTMLInputElement>(null);
  const updateMutation = useUpdateAdmin();
  const pending = updateMutation.isPending;

  const trimmedName = displayName.trim();
  const displayNameChanged = trimmedName !== admin.display_name;
  const roleChanged = role !== admin.role;
  const activeChanged = active !== admin.active;
  const deactivating = admin.active && !active;
  const dirty = displayNameChanged || roleChanged || activeChanged;
  const blockedByConfirmation = deactivating && !deactivateConfirmed;

  const clearServerError = () => {
    if (updateMutation.isError) updateMutation.reset();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (trimmedName.length === 0) {
      setDisplayNameError('Enter a display name.');
      return;
    }
    if (trimmedName.length > ADMIN_DISPLAY_NAME_MAX_LENGTH) {
      setDisplayNameError(`Use ${ADMIN_DISPLAY_NAME_MAX_LENGTH} characters or fewer.`);
      return;
    }
    setDisplayNameError(null);
    if (!dirty || blockedByConfirmation) return;

    const patch: UpdateAdminInput = {};
    if (displayNameChanged) patch.display_name = trimmedName;
    if (roleChanged) patch.role = role;
    if (activeChanged) patch.active = active;

    updateMutation.mutate(
      { adminId: admin.id, patch },
      {
        onSuccess: (updated) => {
          onSaved(updated);
        },
      },
    );
  };

  return (
    <Modal
      labelledBy={titleId}
      initialFocusRef={displayNameRef}
      returnFocusRef={returnFocusRef}
      onClose={onClose}
      closeDisabled={pending}
    >
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Identity
          </p>
          <h2 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Edit admin
          </h2>
          <p className="mt-0.5 break-all font-mono text-[11.5px] text-ink-muted">
            {admin.username}
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={pending}
          aria-label="Close edit admin dialog"
          className="px-1.5 py-1"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <form onSubmit={handleSubmit} className="p-5" noValidate aria-busy={pending}>
        <div>
          <label htmlFor={displayNameId} className="block text-[13px] font-medium text-ink">
            Display name
          </label>
          <input
            ref={displayNameRef}
            id={displayNameId}
            type="text"
            value={displayName}
            onChange={(event) => {
              setDisplayName(event.target.value);
              clearServerError();
            }}
            autoComplete="off"
            disabled={pending}
            aria-invalid={displayNameError !== null}
            aria-describedby={displayNameError === null ? undefined : displayNameErrorId}
            className={FIELD_CLASS}
          />
          {displayNameError !== null && (
            <p id={displayNameErrorId} role="alert" className="mt-1 text-[11.5px] text-danger">
              {displayNameError}
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

        <div className="mt-4 rounded-md border border-line bg-surface-sunken/40 px-3 py-2.5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p id={activeLabelId} className="text-[13px] font-medium text-ink">
                Active
              </p>
              <p id={activeHintId} className="mt-0.5 text-[11.5px] leading-5 text-ink-muted">
                Inactive admins cannot sign in and lose any open session.
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={active}
              aria-labelledby={activeLabelId}
              aria-describedby={activeHintId}
              disabled={pending}
              onClick={() => {
                setActive((current) => !current);
                setDeactivateConfirmed(false);
                clearServerError();
              }}
              className={`relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60 ${
                active ? 'bg-ok' : 'bg-line-strong'
              }`}
            >
              <span
                aria-hidden="true"
                className={`inline-block size-3.5 rounded-full bg-white shadow-sm transition-transform ${
                  active ? 'translate-x-[1.15rem]' : 'translate-x-0.5'
                }`}
              />
            </button>
          </div>

          {deactivating && (
            <div
              role="alert"
              className="mt-3 rounded border border-danger/25 bg-danger-soft/70 px-2.5 py-2"
            >
              <p className="text-[11.5px] leading-5 text-danger">
                Deactivating signs this admin out and blocks new sign-ins.
              </p>
              <label
                htmlFor={confirmId}
                className="mt-2 flex items-start gap-2 text-[11.5px] leading-5 text-ink"
              >
                <input
                  id={confirmId}
                  type="checkbox"
                  checked={deactivateConfirmed}
                  disabled={pending}
                  onChange={(event) => setDeactivateConfirmed(event.target.checked)}
                  className="mt-0.5 size-3.5 accent-danger"
                />
                I understand this admin will be signed out.
              </label>
            </div>
          )}
        </div>

        {updateMutation.isError && (
          <div className="mt-4">
            <RequestErrorPanel error={updateMutation.error} title="Could not update admin" />
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2 border-t border-line pt-4">
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" disabled={pending || !dirty || blockedByConfirmation}>
            {pending ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
