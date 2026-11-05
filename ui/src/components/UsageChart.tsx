import { useState } from 'react';

import type { UsagePoint } from '../api/client';
import { formatCost, formatExactNumber, formatUsageAxis, formatUsageDay } from '../lib/format';
import { usageDayKey } from '../lib/usage';

const CHART_WIDTH = 600;
const CHART_HEIGHT = 160;
const TOP_Y = 12;
const BASELINE_Y = 150;

interface UsageChartProps {
  points: UsagePoint[];
  selectedDay: string | null;
  onSelectDay: (day: string) => void;
}

function barLabel(point: UsagePoint): string {
  const requestsLabel = point.requests === 1 ? 'request' : 'requests';
  return `${formatUsageDay(point.bucket_start)} UTC: ${formatExactNumber(
    point.total_tokens,
  )} total tokens across ${formatExactNumber(point.requests)} ${requestsLabel}`;
}

export function UsageChart({ points, selectedDay, onSelectDay }: UsageChartProps) {
  const [hoveredDay, setHoveredDay] = useState<string | null>(null);

  const firstPoint = points[0];
  const lastPoint = points[points.length - 1];
  if (firstPoint === undefined || lastPoint === undefined) {
    return <p className="py-6 text-center text-[13px] text-ink-muted">No usage in this range.</p>;
  }

  const maxTotal = points.reduce((max, point) => Math.max(max, point.total_tokens), 0);
  const billedTotal = points.reduce((sum, point) => sum + Number(point.billed_cost), 0);
  const slot = CHART_WIDTH / points.length;
  const barWidth = Math.max(1, Math.min(slot * 0.62, 36));
  const middlePoint = points.length >= 3 ? points[Math.floor((points.length - 1) / 2)] : undefined;
  const allZero = maxTotal === 0;
  const selectedIndex = points.findIndex(
    (point) => usageDayKey(point.bucket_start) === selectedDay,
  );
  const selectedCenter = selectedIndex >= 0 ? selectedIndex * slot + slot / 2 : null;

  const chartLabel = `Daily total tokens from ${formatUsageDay(firstPoint.bucket_start)} to ${formatUsageDay(lastPoint.bucket_start)}, UTC`;

  return (
    <div>
      <div role="list" aria-label={chartLabel} className="relative h-36 w-full sm:h-40">
        <svg
          aria-hidden="true"
          viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
          preserveAspectRatio="none"
          className="absolute inset-0 block h-full w-full"
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
          {selectedCenter !== null && (
            <line
              x1={selectedCenter}
              y1={TOP_Y}
              x2={selectedCenter}
              y2={BASELINE_Y}
              strokeDasharray="2 4"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
              className="stroke-line-strong"
            />
          )}
          {points.map((point, index) => {
            const dayKey = usageDayKey(point.bucket_start);
            const selected = selectedDay === dayKey;
            const hovered = hoveredDay === dayKey;
            const height =
              point.total_tokens === 0
                ? 2
                : Math.max(2, (point.total_tokens / Math.max(maxTotal, 1)) * (BASELINE_Y - TOP_Y));
            const x = index * slot + (slot - barWidth) / 2;
            const y = BASELINE_Y - height;
            const fill =
              point.total_tokens === 0
                ? hovered || selected
                  ? 'fill-ink-muted'
                  : 'fill-line-strong'
                : hovered || selected
                  ? 'fill-accent-strong'
                  : 'fill-accent';

            return (
              <g key={point.bucket_start}>
                <rect
                  x={x}
                  y={y}
                  width={barWidth}
                  height={height}
                  rx={Math.min(1.5, barWidth / 2)}
                  className={`${fill} transition-[fill] duration-150 motion-reduce:transition-none`}
                />
                {selected && (
                  <rect
                    x={x - 2}
                    y={y - 2}
                    width={barWidth + 4}
                    height={height + 4}
                    rx={Math.min(2.5, barWidth / 2 + 1)}
                    fill="none"
                    strokeWidth={1.5}
                    vectorEffect="non-scaling-stroke"
                    className="stroke-ink"
                  />
                )}
              </g>
            );
          })}
          {selectedCenter !== null && (
            <path
              d={`M ${selectedCenter - 4} ${BASELINE_Y + 2} L ${selectedCenter + 4} ${
                BASELINE_Y + 2
              } L ${selectedCenter} ${BASELINE_Y + 7} Z`}
              className="fill-ink"
            />
          )}
        </svg>
        <div className="absolute inset-0 flex">
          {points.map((point) => {
            const dayKey = usageDayKey(point.bucket_start);
            const selected = selectedDay === dayKey;
            const label = barLabel(point);

            return (
              <div key={point.bucket_start} role="listitem" className="flex min-w-0 flex-1">
                <button
                  type="button"
                  aria-pressed={selected}
                  aria-current={selected ? 'date' : undefined}
                  aria-label={label}
                  title={label}
                  onClick={() => onSelectDay(dayKey)}
                  onPointerEnter={() => setHoveredDay(dayKey)}
                  onPointerLeave={() =>
                    setHoveredDay((current) => (current === dayKey ? null : current))
                  }
                  onFocus={() => setHoveredDay(dayKey)}
                  onBlur={() => setHoveredDay((current) => (current === dayKey ? null : current))}
                  className="h-full w-full cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent"
                />
              </div>
            );
          })}
        </div>
      </div>
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
      <p className="mt-0.5 font-mono text-[10px] leading-4 text-ink-muted">
        Select a day to drill into its totals and keys.
      </p>
      <p className="mt-0.5 font-mono text-[10px] tabular-nums text-ink-muted">
        Billed cost in this range: {formatCost(String(billedTotal))}
      </p>
      {allZero && (
        <p className="mt-2 text-[11px] text-ink-muted">No tokens recorded in this range.</p>
      )}
    </div>
  );
}
