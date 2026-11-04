import { ROLE_LABELS, type AdminRole } from '../lib/session';

const ROLE_STYLES: Record<AdminRole, string> = {
  owner: 'border-accent/25 bg-accent/10 text-accent',
  operator: 'border-line-strong bg-surface-sunken text-ink',
  auditor: 'border-warn/30 bg-warn-soft text-warn',
};

export function RoleBadge({ role, className = '' }: { role: AdminRole; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.08em] ${ROLE_STYLES[role]} ${className}`}
    >
      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      {ROLE_LABELS[role]}
    </span>
  );
}
