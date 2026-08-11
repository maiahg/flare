import type { TimelineEntry } from "@/lib/api";
import { EmptyState } from "@/components/ui/Panel";
import { absoluteTime } from "@/lib/format";

export function Timeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return (
      <EmptyState>
        <span data-testid="timeline-empty">No timeline entries yet.</span>
      </EmptyState>
    );
  }
  return (
    <ol aria-label="timeline" className="m-0 list-none p-0">
      {entries.map((entry) => (
        <li
          key={entry.id}
          data-testid="timeline-entry"
          className="grid grid-cols-[auto_1fr] items-baseline gap-x-4 border-b border-[var(--border)] py-2.5 last:border-b-0"
        >
          <time className="whitespace-nowrap text-xs tabular-nums text-[var(--muted)]">
            {absoluteTime(entry.occurred_at)}
          </time>
          <div className="min-w-0">
            {entry.entry_type ? (
              <span
                data-testid="entry-type"
                className="mr-2 rounded bg-[var(--tone-neutral-bg)] px-1.5 py-0.5 text-[0.7rem] font-medium text-[var(--tone-neutral-fg)]"
              >
                [{entry.entry_type}]
              </span>
            ) : null}
            <span className="text-sm">{entry.description}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}
