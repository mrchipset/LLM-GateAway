import { ApiRequestError } from '../api/client';
import { Button } from './Button';

interface RequestErrorPanelProps {
  error: Error;
  title: string;
  retryLabel: string;
  onRetry: () => void;
}

export function RequestErrorPanel({ error, title, retryLabel, onRetry }: RequestErrorPanelProps) {
  const requestError = error instanceof ApiRequestError ? error : null;
  const statusLine =
    requestError === null
      ? 'Request failed'
      : requestError.status === 0
        ? 'Network error'
        : `HTTP ${requestError.status}`;
  const code = requestError?.code ?? null;
  const requestId = requestError?.requestId ?? null;

  return (
    <div role="alert" className="rounded-md border border-danger/30 bg-danger-soft/60 p-4">
      <h3 className="text-sm font-semibold text-danger">{title}</h3>
      <p className="mt-1 font-mono text-[11.5px] text-ink">{statusLine}</p>
      <p className="mt-2 text-[13px] text-ink">{requestError?.message ?? error.message}</p>
      {(code !== null || requestId !== null) && (
        <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 border-t border-danger/20 pt-3 font-mono text-[11px]">
          {code !== null && (
            <>
              <dt className="text-ink-muted">Code</dt>
              <dd className="break-all text-ink">{code}</dd>
            </>
          )}
          {requestId !== null && (
            <>
              <dt className="text-ink-muted">Request ID</dt>
              <dd className="select-all break-all text-ink">{requestId}</dd>
            </>
          )}
        </dl>
      )}
      <Button variant="secondary" className="mt-4" onClick={onRetry} aria-label={retryLabel}>
        Retry
      </Button>
    </div>
  );
}
