import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react';

import { buttonClassName, type ButtonVariant } from './buttonStyles';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  ref?: Ref<HTMLButtonElement>;
  children: ReactNode;
}

export function Button({
  variant = 'primary',
  className = '',
  type = 'button',
  ref,
  children,
  ...props
}: ButtonProps) {
  return (
    <button ref={ref} type={type} className={buttonClassName(variant, className)} {...props}>
      {children}
    </button>
  );
}
