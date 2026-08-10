import type { TimelineEntry } from "@/lib/api";

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

export function Timeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return <p data-testid="timeline-empty">No timeline entries yet.</p>;
  }
  return (
    <ol aria-label="timeline" style={{ listStyle: "none", padding: 0 }}>
      {entries.map((entry) => (
        <li
          key={entry.id}
          data-testid="timeline-entry"
          style={{ padding: "0.5rem 0", borderBottom: "1px solid #222" }}
        >
          <time style={{ opacity: 0.6, fontVariantNumeric: "tabular-nums" }}>
            {formatWhen(entry.occurred_at)}
          </time>
          {entry.entry_type ? (
            <span
              data-testid="entry-type"
              style={{ margin: "0 0.5rem", opacity: 0.8 }}
            >
              [{entry.entry_type}]
            </span>
          ) : null}
          <span>{entry.description}</span>
        </li>
      ))}
    </ol>
  );
}