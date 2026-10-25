import { formatCompactNumber, formatExactNumber } from '../lib/format';

interface CompactNumberProps {
  value: number;
  unit: string;
  className?: string;
}

export function CompactNumber({ value, unit, className = '' }: CompactNumberProps) {
  const exact = formatExactNumber(value);
  const compact = formatCompactNumber(value);

  if (compact === exact) {
    return (
      <span className={`tabular-nums ${className}`} title={`${exact} ${unit}`}>
        {exact}
      </span>
    );
  }

  return (
    <span className={`tabular-nums ${className}`} title={`${exact} ${unit}`}>
      <span aria-hidden="true">{compact}</span>
      <span className="sr-only">{exact}</span>
    </span>
  );
}
