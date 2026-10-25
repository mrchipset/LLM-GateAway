import type { BackendStatus } from '../hooks/useBackendStatus';
import { StatusPanel } from './StatusPanel';

interface HeaderProps {
  status: BackendStatus;
}

export function Header({ status }: HeaderProps) {
  return (
    <header className="flex animate-rise flex-col gap-6 border-b border-line pb-6 lg:flex-row lg:items-start lg:justify-between">
      <div>
        <p className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-ink-muted">
          Admin console
        </p>
        <h1 className="mt-2 text-[27px] font-semibold leading-none tracking-[-0.025em] text-ink">
          LLM-GateAway
        </h1>
        <p className="mt-3 font-mono text-xs text-ink-muted">
          Backend version{' '}
          <span className="text-ink">{status.version ? `v${status.version}` : '—'}</span>
        </p>
      </div>
      <StatusPanel status={status} />
    </header>
  );
}
