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

export function AuditIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M2.4 8a5.6 5.6 0 1 0 1.7-4" />
      <path d="M2.4 2.3v3h3" />
      <path d="M8 4.9V8l2.1 1.3" />
    </svg>
  );
}

export function AdminsIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <circle cx="6" cy="5.4" r="2.1" />
      <path d="M2.4 13.2c0-2 1.6-3.4 3.6-3.4s3.6 1.4 3.6 3.4" />
      <path d="M10.4 4.2a1.9 1.9 0 0 1 0 3.6" />
      <path d="M11.4 9.9c1.4.3 2.4 1.5 2.4 3.3" />
    </svg>
  );
}

export function AdminAuditIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M3.4 2.4h9.2v11.2H3.4V2.4Z" />
      <path d="M5.6 5.4h4.8M5.6 8h4.8M5.6 10.6h2.8" />
    </svg>
  );
}

export function LockIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <rect x="3.4" y="7" width="9.2" height="6.4" rx="1.2" />
      <path d="M5.7 7V5.2a2.3 2.3 0 0 1 4.6 0V7" />
    </svg>
  );
}

export function PlusIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M8 3.2v9.6M3.2 8h9.6" />
    </svg>
  );
}

export function BackIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M9.7 3.3 5 8l4.7 4.7" />
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

export function BillingIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <rect x="2.4" y="3.1" width="11.2" height="9.8" rx="1.4" />
      <path d="M2.4 6.4h11.2" />
      <path d="M5.2 9.2h2.4M9.8 9.2h1" />
    </svg>
  );
}

export function TagIcon({ className }: IconProps) {
  return (
    <svg {...iconProps} className={className}>
      <path d="M2.7 8.2 8.2 2.7h4.9v4.9l-5.5 5.5a1.2 1.2 0 0 1-1.7 0l-3.2-3.2a1.2 1.2 0 0 1 0-1.7Z" />
      <circle cx="10.4" cy="5.3" r="0.9" />
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
