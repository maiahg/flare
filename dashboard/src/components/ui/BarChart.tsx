export type Bar = { label: string; value: number; color: string };

/** Round the axis top up to a friendly 1/2/5 × 10^n so ticks stay readable. */
function niceMax(max: number): number {
  if (max <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  const scaled = max / magnitude;
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
  return step * magnitude;
}

export function BarChart({
  bars,
  height = 190,
  ariaLabel = "chart",
}: {
  bars: Bar[];
  height?: number;
  ariaLabel?: string;
}) {
  const top = niceMax(Math.max(0, ...bars.map((b) => b.value)));
  const ticks = [top, top * 0.66, top * 0.33, 0];

  return (
    <figure aria-label={ariaLabel} className="m-0">
      <div className="flex gap-3" style={{ height }}>
        <div className="flex w-9 flex-col justify-between text-right text-[0.7rem] tabular-nums text-[var(--muted)]">
          {ticks.map((t) => (
            <span key={t}>{Math.round(t)}</span>
          ))}
        </div>

        <div className="relative flex-1">
          {ticks.map((t, i) => (
            <div
              key={t}
              className="absolute inset-x-0 border-t border-dashed border-[var(--border)]"
              style={{ top: `${(i / (ticks.length - 1)) * 100}%` }}
            />
          ))}

          <div className="absolute inset-0 flex items-end justify-around gap-4 px-2">
            {bars.map((bar) => (
              <div
                key={bar.label}
                data-testid={`bar-${bar.label.toLowerCase()}`}
                className="flex h-full min-w-0 flex-1 flex-col justify-end items-center"
              >
                <span className="mb-1 text-xs font-semibold tabular-nums">
                  {bar.value}
                </span>
                <div
                  className="w-full max-w-24 rounded-t-sm"
                  style={{
                    // 3px floor keeps an empty category visible as a baseline.
                    height: `max(3px, ${(bar.value / top) * 88}%)`,
                    background: bar.color,
                  }}
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-2 flex gap-3">
        <div className="w-9" />
        <div className="flex flex-1 justify-around gap-4 px-2">
          {bars.map((bar) => (
            <span
              key={bar.label}
              className="min-w-0 flex-1 truncate text-center text-xs text-[var(--muted)]"
            >
              {bar.label}
            </span>
          ))}
        </div>
      </div>
    </figure>
  );
}
