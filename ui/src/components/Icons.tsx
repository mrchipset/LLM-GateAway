interface IconProps {
  className?: string;
}

const iconProps = {
  viewBox: '0 0 16 16',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  focusable: 'false',
  'aria-hidden': true,
} as const;

export function CheckCircleIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <circle cx="8" cy="8" r="6.25" />
      <path d="m5.4 8.2 1.8 1.8 3.5-3.8" />
    </svg>
  );
}

export function AlertTriangleIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M7.1 2.6 1.7 12a1 1 0 0 0 .9 1.5h10.8a1 1 0 0 0 .9-1.5L8.9 2.6a1 1 0 0 0-1.8 0Z" />
      <path d="M8 6.2v3.1" />
      <circle cx="8" cy="11.4" r="0.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function OfflineIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <circle cx="8" cy="8" r="6.25" />
      <path d="m3.8 12.2 8.4-8.4" />
    </svg>
  );
}

export function ClockIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <circle cx="8" cy="8" r="6.25" strokeDasharray="2.4 2.6" />
      <path d="M8 5v3.4l2 1.2" />
    </svg>
  );
}

export function RefreshIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M13.3 6.6A5.3 5.3 0 1 0 13 10.2" />
      <path d="M13.6 2.9v3.8h-3.8" />
    </svg>
  );
}

export function KeyIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <circle cx="5.2" cy="10.8" r="2.7" />
      <path d="m7.3 8.8 5.5-5.5M10.7 5.2l1.5 1.5M11.9 4l1.4 1.4" />
    </svg>
  );
}

export function ModelsIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M2.2 4.1 8 1.5l5.8 2.6L8 6.7 2.2 4.1Z" />
      <path d="M2.2 8 8 10.6 13.8 8" />
      <path d="M2.2 11.9 8 14.5l5.8-2.6" />
    </svg>
  );
}

export function UsageIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M3 13V9" />
      <path d="M8 13V4" />
      <path d="M13 13V6.5" />
    </svg>
  );
}

export function AccessIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M8 1.8 13 3.6v4.1c0 3.1-2.1 5.3-5 6.5-2.9-1.2-5-3.4-5-6.5V3.6L8 1.8Z" />
      <path d="m5.8 8.1 1.4 1.4 3-3.2" />
    </svg>
  );
}

export function EditIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="m10.9 2.9 2.2 2.2-7.4 7.4-2.9.7.7-2.9 7.4-7.4Z" />
      <path d="m9.6 4.2 2.2 2.2" />
    </svg>
  );
}

export function CloseIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="m4 4 8 8M12 4l-8 8" />
    </svg>
  );
}

export function CopyIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <rect x="5.4" y="5.4" width="8.1" height="8.1" rx="1.4" />
      <path d="M10.7 5.4V3.9c0-.7-.6-1.3-1.3-1.3H3.9c-.7 0-1.3.6-1.3 1.3v5.5c0 .7.6 1.3 1.3 1.3h1.5" />
    </svg>
  );
}

export function TrashIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M2.8 4.2h10.4" />
      <path d="M6 4.2V2.9c0-.5.4-.9.9-.9h2.2c.5 0 .9.4.9.9v1.3" />
      <path d="m4.3 4.2.6 8.5c0 .6.5 1.1 1.1 1.1h4c.6 0 1.1-.5 1.1-1.1l.6-8.5" />
      <path d="M6.8 6.8v4.4M9.2 6.8v4.4" />
    </svg>
  );
}
