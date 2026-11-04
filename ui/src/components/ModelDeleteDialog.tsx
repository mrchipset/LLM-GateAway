import { useId, useRef, type RefObject } from 'react';

import { ApiRequestError, type ModelSummary } from '../api/client';
import { useDeleteModel } from '../hooks/useModelMutations';
import { Button } from './Button';
import { AlertTriangleIcon, CloseIcon } from './Icons';
import { Modal } from './Modal';
import { RequestErrorPanel } from './RequestErrorPanel';

interface ModelDeleteDialogProps {
  model: ModelSummary;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onDeleted: (model: ModelSummary) => void;
  onStale: () => void;
}

export function ModelDeleteDialog({
  model,
  returnFocusRef,
  onClose,
  onDeleted,
  onStale,
}: ModelDeleteDialogProps) {
  const titleId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const deleteMutation = useDeleteModel();
  const pending = deleteMutation.isPending;

  const handleDelete = () => {
    deleteMutation.mutate(model.id, {
      onSuccess: () => {
        onDeleted(model);
      },
      onError: (error) => {
        if (error instanceof ApiRequestError && error.status === 404) {
          onStale();
        }
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
            Registry
          </p>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold text-ink">
            Delete model
          </h3>
          <p className="mt-1 break-words text-[11.5px] text-ink-muted">
            <span className="font-mono text-ink">{model.id}</span> · {model.provider}
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={onClose}
          disabled={pending}
          aria-label="Close delete model dialog"
          className="shrink-0 px-2"
        >
          <CloseIcon className="size-4" />
        </Button>
      </div>

      <div className="px-5 py-4">
        <p className="flex items-start gap-2 rounded border border-danger/30 bg-danger-soft/60 px-2.5 py-2 text-[12px] text-danger">
          <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Requests using this model will fail immediately. Tenants that allowlist it lose access
            to it. This action cannot be undone.
          </span>
        </p>

        <p className="mt-3 text-[12px] text-ink-muted">
          Upstream model <span className="font-mono text-ink">{model.upstream_model}</span>
        </p>

        {deleteMutation.isError && deleteMutation.error !== null && (
          <div className="mt-3">
            <RequestErrorPanel error={deleteMutation.error} title="Could not delete model" />
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2 border-t border-line pt-3">
          <Button ref={cancelRef} variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button
            onClick={handleDelete}
            disabled={pending}
            className="bg-danger text-white hover:bg-danger/90 disabled:bg-line-strong disabled:text-ink-muted"
          >
            {pending ? 'Deleting…' : 'Delete model'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
