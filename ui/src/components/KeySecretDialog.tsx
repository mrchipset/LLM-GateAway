import { useEffect, useId, useRef, useState, type RefObject } from 'react';

import type { CreatedApiKey } from '../api/client';
import { Button } from './Button';
import { AlertTriangleIcon, CheckCircleIcon, CloseIcon, CopyIcon } from './Icons';
import { Modal } from './Modal';

type CopyStatus = 'idle' | 'copied' | 'failed';

interface KeySecretDialogProps {
  created: CreatedApiKey;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
}

export function KeySecretDialog({ created, returnFocusRef, onClose }: KeySecretDialogProps) {
  const [copyStatus, setCopyStatus] = useState<CopyStatus>('idle');
  const [confirmingClose, setConfirmingClose] = useState(false);
  const titleId = useId();
  const copyButtonRef = useRef<HTMLButtonElement>(null);
  const keepKeyRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (confirmingClose) keepKeyRef.current?.focus();
  }, [confirmingClose]);

  const requestClose = () => {
    if (copyStatus === 'copied') {
      onClose();
      return;
    }
    setConfirmingClose(true);
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(created.key);
      setCopyStatus('copied');
      setConfirmingClose(false);
    } catch {
      setCopyStatus('failed');
    }
  };

  const handleKeepKey = () => {
    setConfirmingClose(false);
    copyButtonRef.current?.focus();
  };

  return (
    <Modal
      labelledBy={titleId}
      onClose={requestClose}
      initialFocusRef={copyButtonRef}
      returnFocusRef={returnFocusRef}
    >
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
            Access
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            API key created
          </h3>
          <p className="mt-1 break-words text-[11.5px] text-ink-muted">
            {created.name} · <span className="font-mono">{created.key_prefix}</span>
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={requestClose}
          aria-label="Close API key dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <div className="px-5 py-4">
        <p className="flex items-start gap-2 rounded border border-warn/30 bg-warn-soft px-2.5 py-2 text-[11.5px] text-warn">
          <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Copy this key now. It is shown only once and cannot be retrieved after you close this
            dialog.
          </span>
        </p>

        <div className="mt-3 rounded-md border border-line-strong bg-surface-sunken px-3 py-2">
          <code className="block select-all break-all font-mono text-[12.5px] leading-6 text-ink">
            {created.key}
          </code>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button ref={copyButtonRef} onClick={() => void handleCopy()}>
            <CopyIcon className="size-3.5" />
            Copy key
          </Button>
          <p
            role="status"
            className={`flex items-center gap-1.5 text-[12px] ${
              copyStatus === 'failed' ? 'text-danger' : 'text-ok'
            }`}
          >
            {copyStatus === 'copied' && (
              <>
                <CheckCircleIcon className="size-3.5" />
                Copied to clipboard.
              </>
            )}
            {copyStatus === 'failed' && (
              <>
                <AlertTriangleIcon className="size-3.5" />
                Copy failed. Select the key and copy it manually.
              </>
            )}
          </p>
        </div>

        {confirmingClose ? (
          <div className="mt-4 border-t border-line pt-3">
            <p role="alert" className="text-[12px] font-medium text-ink">
              You have not copied this key. Close anyway?
            </p>
            <div className="mt-2 flex flex-wrap justify-end gap-2">
              <Button ref={keepKeyRef} variant="secondary" onClick={handleKeepKey}>
                Keep key
              </Button>
              <Button
                onClick={onClose}
                className="bg-danger text-white hover:bg-danger/90 disabled:bg-line-strong disabled:text-ink-muted"
              >
                Close without copying
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-4 flex justify-end border-t border-line pt-3">
            <Button variant="secondary" onClick={requestClose}>
              Close
            </Button>
          </div>
        )}
      </div>
    </Modal>
  );
}
