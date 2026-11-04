import type { BackendStatus } from '../hooks/useBackendStatus';
import type { AdminSession } from '../lib/session';
import { Button } from './Button';
import { RoleBadge } from './RoleBadge';
import { StatusPanel } from './StatusPanel';

interface HeaderProps {
  status: BackendStatus;
  session: AdminSession;
  signingOut: boolean;
  onSignOut: () => void;
}

export function Header({ status, session, signingOut, onSignOut }: HeaderProps) {
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

      <div className="flex w-full flex-col gap-3 lg:w-auto lg:items-end">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-surface px-3 py-2 lg:justify-end">
          <div className="min-w-0">
            <p className="font-mono text-[9.5px] font-medium uppercase tracking-[0.14em] text-ink-muted">
              Signed in
            </p>
            <p className="truncate text-[13px] font-medium leading-tight text-ink">
              {session.name}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <RoleBadge role={session.role} />
            <Button
              variant="ghost"
              onClick={onSignOut}
              disabled={signingOut}
              className="px-2 py-1 text-[12px]"
            >
              {signingOut ? 'Signing out…' : 'Sign out'}
            </Button>
          </div>
        </div>
        <StatusPanel status={status} />
      </div>
    </header>
  );
}
