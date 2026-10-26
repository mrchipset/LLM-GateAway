import { useId, useRef, type RefObject } from 'react';

import type { ApiKeySummary } from '../api/client';
import { useRevokeKey } from '../hooks/useKeyMutations';
import { Button } from './Button';
import { AlertTriangleIcon, CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface KeyRevokeDialogProps {
  masterKey: string;
  apiKey: ApiKeySummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onRevoked: () => void;
}

export function KeyRevokeDialog({
  masterKey,
  apiKey,
  returnFocusRef,
  onClose,
  onRevoked,
}: KeyRevokeDialogProps) {
  const titleId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const revokeMutation = useRevokeKey(masterKey);
  const pending = revokeMutation.isPending;

  const handleRevoke = () => {
    revokeMutation.mutate(apiKey.id, {
      onSuccess: () => {
        onRevoked();
      },
    });
  };

  return (
    <Modal
      labelledBy={titleId}
      onClose={onClose}
      closeDisabled={pending}
      initialFocusRef={cancelRef}
      returnFocusRef={returnFocusRef}
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Access
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Revoke API key
          </h3>
          <p className="mt-1 break-words text-[11.5px] text-ink-muted">
            {apiKey.name} · <span className="font-mono">{apiKey.key_prefix}</span>
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={pending}
          aria-label="Close revoke key dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <div className="px-5 py-4">
        <p className="flex items-start gap-2 rounded border border-danger/30 bg-danger-soft/60 px-2.5 py-2 text-[12px] text-danger">
          <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Clients using this key will be rejected immediately. This action cannot be undone.
          </span>
        </p>

        {revokeMutation.isError && revokeMutation.error !== null && (
          <div className="mt-3">
            <RequestErrorPanel error={revokeMutation.error} title="Could not revoke API key" />
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2 border-t border-line pt-3">
          <Button ref={cancelRef} variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button
            onClick={handleRevoke}
            disabled={pending}
            className="bg-danger text-white hover:bg-danger/90 disabled:bg-line-strong disabled:text-ink-muted"
          >
            {pending ? 'Revoking...' : 'Revoke key'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
