import type { ReactNode } from 'react';

interface PanelProps {
  labelledBy: string;
  children: ReactNode;
}

export function Panel({ labelledBy, children }: PanelProps) {
  return (
    <section
      aria-labelledby={labelledBy}
      className="min-w-0 rounded-lg border border-line bg-surface shadow-[0_1px_2px_rgba(22,24,26,0.04)]"
    >
      {children}
    </section>
  );
}

interface PanelHeaderProps {
  id: string;
  eyebrow: string;
  title: string;
  children?: ReactNode;
}

export function PanelHeader({ id, eyebrow, title, children }: PanelHeaderProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line px-5 py-3.5">
      <div>
        <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-ink-muted">
          {eyebrow}
        </p>
        <h2
          id={id}
          className="mt-0.5 text-[15px] font-semibold leading-tight tracking-[-0.01em] text-ink"
        >
          {title}
        </h2>
      </div>
      {children}
    </div>
  );
}
