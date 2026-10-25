import type { UsagePoint } from '../api/client';
import { formatExactNumber, formatUsageAxis, formatUsageDay } from '../lib/format';

const CHART_WIDTH = 600;
const CHART_HEIGHT = 160;
const TOP_Y = 12;
const BASELINE_Y = 150;

interface UsageChartProps {
  points: UsagePoint[];
}

export function UsageChart({ points }: UsageChartProps) {
  const firstPoint = points[0];
  const lastPoint = points[points.length - 1];
  if (firstPoint === undefined || lastPoint === undefined) {
    return <p className="py-6 text-center text-[13px] text-ink-muted">No usage in this range.</p>;
  }

  const maxTotal = points.reduce((max, point) => Math.max(max, point.total_tokens), 0);
  const slot = CHART_WIDTH / points.length;
  const barWidth = Math.max(1, Math.min(slot * 0.62, 36));
  const middlePoint = points.length >= 3 ? points[Math.floor((points.length - 1) / 2)] : undefined;
  const allZero = maxTotal === 0;

  const chartLabel = `Daily total tokens from ${formatUsageDay(firstPoint.bucket_start)} to ${formatUsageDay(lastPoint.bucket_start)}, UTC`;

  return (
    <div>
      <svg
        role="list"
        aria-label={chartLabel}
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        preserveAspectRatio="none"
        className="block h-36 w-full sm:h-40"
        focusable="false"
      >
        <line
          x1={0}
          y1={TOP_Y}
          x2={CHART_WIDTH}
          y2={TOP_Y}
          strokeDasharray="2 5"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
          className="stroke-line"
        />
        <line
          x1={0}
          y1={BASELINE_Y}
          x2={CHART_WIDTH}
          y2={BASELINE_Y}
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
          className="stroke-line-strong"
        />
        {points.map((point, index) => {
          const height =
            point.total_tokens === 0
              ? 2
              : Math.max(2, (point.total_tokens / Math.max(maxTotal, 1)) * (BASELINE_Y - TOP_Y));
          const x = index * slot + (slot - barWidth) / 2;
          const y = BASELINE_Y - height;
          const requestsLabel = point.requests === 1 ? 'request' : 'requests';
          const barLabel = `${formatUsageDay(point.bucket_start)} UTC: ${formatExactNumber(
            point.total_tokens,
          )} total tokens across ${formatExactNumber(point.requests)} ${requestsLabel}`;

          return (
            <g key={point.bucket_start} role="listitem" aria-label={barLabel} className="group">
              <title>{barLabel}</title>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={height}
                rx={Math.min(1.5, barWidth / 2)}
                className={`transition-[fill] duration-150 motion-reduce:transition-none ${
                  point.total_tokens === 0
                    ? 'fill-line-strong group-hover:fill-ink-muted'
                    : 'fill-accent group-hover:fill-accent-strong'
                }`}
              />
            </g>
          );
        })}
      </svg>
      <div
        aria-hidden="true"
        className="mt-1.5 grid grid-cols-3 gap-2 font-mono text-[10px] tabular-nums text-ink-muted"
      >
        <span>{points.length > 1 ? formatUsageAxis(firstPoint.bucket_start) : ''}</span>
        <span className="text-center">
          {middlePoint !== undefined
            ? formatUsageAxis(middlePoint.bucket_start)
            : points.length === 1
              ? formatUsageAxis(firstPoint.bucket_start)
              : ''}
        </span>
        <span className="text-right">
          {points.length > 1 ? formatUsageAxis(lastPoint.bucket_start) : ''}
        </span>
      </div>
      <p className="mt-1.5 font-mono text-[10px] leading-4 text-ink-muted">
        Last bar covers today so far (UTC).
      </p>
      {allZero && (
        <p className="mt-2 text-[11px] text-ink-muted">No tokens recorded in this range.</p>
      )}
    </div>
  );
}
