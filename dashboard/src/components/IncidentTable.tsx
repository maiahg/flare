import Link from "next/link";

import { StatusPill } from "@/components/ui/StatusPill";
import { EmptyState } from "@/components/ui/Panel";
import type { Incident } from "@/lib/api";
import { absoluteTime, describeSource, relativeTime } from "@/lib/format";

function occurredAt(incident: Incident): string | null | undefined {
  return incident.started_at ?? incident.detected_at ?? incident.created_at;
}

export function IncidentTable({
  incidents,
  showMode = true,
}: {
  incidents: Incident[];
  showMode?: boolean;
}) {
  if (incidents.length === 0) {
    return <EmptyState>No incidents yet.</EmptyState>;
  }
  return (
    <table aria-label="incidents" className="w-full border-collapse text-sm">
      <thead>
        <tr className="bg-[var(--surface-muted)] text-left">
          <th className="eyebrow px-4 py-2 font-semibold">When</th>
          <th className="eyebrow px-4 py-2 font-semibold">Title</th>
          {showMode ? (
            <th className="eyebrow px-4 py-2 font-semibold">Mode</th>
          ) : null}
          <th className="eyebrow px-4 py-2 font-semibold">Status</th>
        </tr>
      </thead>
      <tbody>
        {incidents.map((incident) => (
          <tr
            key={incident.id}
            data-testid="incident-row"
            className="border-t border-[var(--border)] transition-colors hover:bg-[var(--surface-muted)]"
          >
            <td
              className="whitespace-nowrap px-4 py-3 align-top text-[var(--muted)] tabular-nums"
              title={absoluteTime(occurredAt(incident))}
            >
              {relativeTime(occurredAt(incident))}
            </td>
            <td className="px-4 py-3 align-top">
              <Link
                href={`/incidents/${incident.id}`}
                className="font-medium text-[var(--accent)] hover:underline"
              >
                {incident.title}
              </Link>
              <div className="mt-0.5 text-xs text-[var(--muted)]">
                {[incident.severity, describeSource(incident.source)]
                  .filter(Boolean)
                  .join(" · ") || "no severity set"}
              </div>
            </td>
            {showMode ? (
              <td className="px-4 py-3 align-top">
                <StatusPill status={incident.mode} />
              </td>
            ) : null}
            <td className="px-4 py-3 align-top">
              <StatusPill status={incident.status} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
