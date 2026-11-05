import { useId, useRef, useState, type FormEvent, type RefObject } from 'react';

import type { AdminSummary } from '../api/client';
import { useUpdateAdmin } from '../hooks/useAdmins';
import { ADMIN_PASSWORD_MAX_LENGTH, ADMIN_PASSWORD_MIN_LENGTH } from '../lib/admins';
import { Button } from './Button';
import { CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface AdminPasswordDialogProps {
  admin: AdminSummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onReset: (message: string) => void;
}

const FIELD_CLASS =
  'mt-1 block w-full min-w-0 rounded-md border border-line-strong bg-white px-2.5 py-1.5 font-mono text-[13px] text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15';

export function AdminPasswordDialog({
  admin,
  returnFocusRef,
  onClose,
  onReset,
}: AdminPasswordDialogProps) {
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [confirmationError, setConfirmationError] = useState<string | null>(null);
  const titleId = useId();
  const passwordId = useId();
  const passwordHintId = useId();
  const passwordErrorId = useId();
  const confirmationId = useId();
  const confirmationErrorId = useId();
  const passwordRef = useRef<HTMLInputElement>(null);
  const updateMutation = useUpdateAdmin();
  const pending = updateMutation.isPending;

  const clearServerError = () => {
    if (updateMutation.isError) updateMutation.reset();
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    let invalid = false;
    if (password.length < ADMIN_PASSWORD_MIN_LENGTH) {
      setPasswordError(`Use at least ${ADMIN_PASSWORD_MIN_LENGTH} characters.`);
      invalid = true;
    } else if (password.length > ADMIN_PASSWORD_MAX_LENGTH) {
      setPasswordError(`Use ${ADMIN_PASSWORD_MAX_LENGTH} characters or fewer.`);
      invalid = true;
    } else {
      setPasswordError(null);
    }

    if (confirmation !== password) {
      setConfirmationError('Passwords do not match.');
      invalid = true;
    } else {
      setConfirmationError(null);
    }

    if (invalid) return;

    updateMutation.mutate(
      { adminId: admin.id, patch: { password } },
      {
        onSuccess: () => {
          onReset(`Password reset for ${admin.username}. Their sessions were revoked.`);
        },
      },
    );
  };

  return (
    <Modal
      labelledBy={titleId}
      initialFocusRef={passwordRef}
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
            Reset password
          </h2>
          <p className="mt-0.5 break-all font-mono text-[11.5px] text-ink-muted">
            {admin.username}
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={pending}
          aria-label="Close reset password dialog"
          className="px-1.5 py-1"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <form onSubmit={handleSubmit} className="p-5" noValidate aria-busy={pending}>
        <p className="rounded border border-warn/30 bg-warn-soft px-2.5 py-1.5 text-[11.5px] leading-5 text-warn">
          The new password replaces the old one immediately and signs this admin out everywhere. It
          is write-only and never displayed.
        </p>

        <div className="mt-4">
          <label htmlFor={passwordId} className="block text-[13px] font-medium text-ink">
            New password
          </label>
          <input
            ref={passwordRef}
            id={passwordId}
            type="password"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              clearServerError();
            }}
            disabled={pending}
            autoComplete="new-password"
            aria-invalid={passwordError !== null}
            aria-describedby={
              passwordError === null ? passwordHintId : `${passwordHintId} ${passwordErrorId}`
            }
            className={FIELD_CLASS}
          />
          <p id={passwordHintId} className="mt-1 text-[11.5px] text-ink-muted">
            At least {ADMIN_PASSWORD_MIN_LENGTH} characters.
          </p>
          {passwordError !== null && (
            <p id={passwordErrorId} role="alert" className="mt-1 text-[11.5px] text-danger">
              {passwordError}
            </p>
          )}
        </div>

        <div className="mt-4">
          <label htmlFor={confirmationId} className="block text-[13px] font-medium text-ink">
            Confirm password
          </label>
          <input
            id={confirmationId}
            type="password"
            value={confirmation}
            onChange={(event) => {
              setConfirmation(event.target.value);
              clearServerError();
            }}
            disabled={pending}
            autoComplete="new-password"
            aria-invalid={confirmationError !== null}
            aria-describedby={confirmationError === null ? undefined : confirmationErrorId}
            className={FIELD_CLASS}
          />
          {confirmationError !== null && (
            <p id={confirmationErrorId} role="alert" className="mt-1 text-[11.5px] text-danger">
              {confirmationError}
            </p>
          )}
        </div>

        {updateMutation.isError && (
          <div className="mt-4">
            <RequestErrorPanel error={updateMutation.error} title="Could not reset password" />
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2 border-t border-line pt-4">
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" disabled={pending || password === '' || confirmation === ''}>
            {pending ? 'Resetting…' : 'Reset password'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
