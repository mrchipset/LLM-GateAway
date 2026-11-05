export type ButtonVariant = 'primary' | 'secondary' | 'ghost';

const BASE =
  'inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed';

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-white hover:bg-accent-strong disabled:bg-line-strong disabled:text-ink-muted',
  secondary:
    'border border-line-strong bg-surface text-ink hover:bg-surface-sunken disabled:border-line disabled:bg-surface-sunken disabled:text-ink-muted',
  ghost: 'text-ink-muted hover:bg-surface-sunken hover:text-ink disabled:text-ink-muted/60',
};

/** Keeps links that start a full-page navigation visually identical to buttons. */
export function buttonClassName(variant: ButtonVariant = 'primary', className = ''): string {
  return `${BASE} ${VARIANTS[variant]} ${className}`;
}
