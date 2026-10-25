import type { BackendState, BackendStatus } from '../hooks/useBackendStatus';
import { Button } from './Button';
import { AlertTriangleIcon, CheckCircleIcon, ClockIcon, OfflineIcon, RefreshIcon } from './Icons';

const TONES = {
  checking: {
    card: 'border-l-line-strong',
    icon: 'bg-surface-sunken text-ink-muted',
    label: 'text-ink',
  },
  healthy: {
    card: 'border-l-ok',
    icon: 'bg-ok-soft text-ok',
    label: 'text-ok',
  },
  degraded: {
    card: 'border-l-warn',
    icon: 'bg-warn-soft text-warn',
    label: 'text-warn',
  },
  offline: {
    card: 'border-l-danger',
    icon: 'bg-danger-soft text-danger',
    label: 'text-danger',
  },
} as const;

const LABELS = {
  checking: 'Checking backend',
  healthy: 'Healthy',
  degraded: 'Readiness degraded',
  offline: 'Backend unreachable',
} as const;

const DETAILS = {
  checking: 'Waiting for /healthz and /readyz.',
  healthy: 'Liveness and readiness are ok.',
  degraded: 'Readiness is unavailable.',
  offline: 'No healthy response from /healthz.',
} as const;

function StatusIcon({ phase }: { phase: BackendState['phase'] }) {
  if (phase === 'healthy') return <CheckCircleIcon className="size-4" />;
  if (phase === 'degraded') return <AlertTriangleIcon className="size-4" />;
  if (phase === 'offline') return <OfflineIcon className="size-4" />;
  return <ClockIcon className="size-4" />;
}

interface StatusPanelProps {
  status: BackendStatus;
}

export function StatusPanel({ status }: StatusPanelProps) {
  const { state, isRetrying, retry } = status;
  const tone = TONES[state.phase];
  const failedChecks = state.phase === 'degraded' ? state.failedChecks : [];
  const detail =
    state.phase === 'degraded' && state.detail === 'unreachable'
      ? 'The readiness check did not respond.'
      : DETAILS[state.phase];

  return (
    <section
      aria-label="Backend status"
      className={`w-full rounded-lg border border-line border-l-[3px] bg-surface p-4 lg:w-[21rem] ${tone.card}`}
    >
      <div role="status" aria-live="polite" aria-atomic="true" className="flex items-start gap-3">
        <span
          className={`mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md ${tone.icon}`}
        >
          <StatusIcon phase={state.phase} />
        </span>
        <div className="min-w-0">
          <p className={`text-sm font-semibold ${tone.label}`}>{LABELS[state.phase]}</p>
          <p className="mt-0.5 text-xs leading-5 text-ink-muted">{detail}</p>
          {failedChecks.length > 0 && (
            <div className="mt-2">
              <p className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted">
                Failed checks
              </p>
              <ul className="mt-1 space-y-0.5">
                {failedChecks.map((check) => (
                  <li key={check.name} className="font-mono text-[11.5px] text-ink">
                    {check.name} <span className="text-warn">= {check.value}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
      {state.phase === 'offline' && (
        <Button
          variant="secondary"
          className="mt-3 w-full"
          onClick={() => void retry()}
          disabled={isRetrying}
          aria-label="Retry health check"
        >
          <RefreshIcon
            className={`size-3.5 ${isRetrying ? 'animate-spin motion-reduce:animate-none' : ''}`}
          />
          {isRetrying ? 'Retrying…' : 'Retry'}
        </Button>
      )}
    </section>
  );
}
