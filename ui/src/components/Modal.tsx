import { useEffect, useRef, type KeyboardEvent, type ReactNode, type RefObject } from 'react';

interface ModalProps {
  labelledBy: string;
  onClose: () => void;
  closeDisabled?: boolean;
  initialFocusRef?: RefObject<HTMLElement | null>;
  returnFocusRef?: RefObject<HTMLElement | null>;
  panelClassName?: string;
  children: ReactNode;
}

export function Modal({
  labelledBy,
  onClose,
  closeDisabled = false,
  initialFocusRef,
  returnFocusRef,
  panelClassName = 'max-w-lg',
  children,
}: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  useEffect(() => {
    const initialFocusTarget = initialFocusRef?.current;
    const returnFocusTarget = returnFocusRef?.current;
    const target = initialFocusTarget ?? panelRef.current;
    target?.focus();
    return () => {
      if (returnFocusTarget?.isConnected) {
        returnFocusTarget.focus();
      }
    };
  }, [initialFocusRef, returnFocusRef]);

  // A dialog can remove or replace the control that had focus, for example after a
  // successful delete or a view switch. Keep keyboard focus inside the dialog instead
  // of letting it fall back to the document body.
  useEffect(() => {
    const panel = panelRef.current;
    if (panel === null) return;
    const activeElement = document.activeElement;
    if (activeElement !== null && panel.contains(activeElement)) return;
    if (
      activeElement === null ||
      activeElement === document.body ||
      activeElement === document.documentElement
    ) {
      panel.focus();
    }
  });

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      if (!closeDisabled) {
        event.preventDefault();
        onClose();
      }
      return;
    }
    if (event.key !== 'Tab') return;

    const focusables = panelRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), [href], select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    if (focusables === undefined || focusables.length === 0) return;

    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (first === undefined || last === undefined) return;

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/35 p-4"
      onKeyDown={handleKeyDown}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
        className={`max-h-[calc(100dvh-2rem)] w-full overflow-y-auto rounded-lg border border-line bg-surface shadow-[0_18px_50px_rgba(22,24,26,0.18)] focus:outline-none ${panelClassName}`}
      >
        {children}
      </div>
    </div>
  );
}
