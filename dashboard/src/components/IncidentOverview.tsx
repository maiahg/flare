import type { IncidentDetail } from "@/lib/api";
import { absoluteTime, describeSource, relativeTime } from "@/lib/format";
import { Panel } from "@/components/ui/Panel";
import { StatusPill } from "@/components/ui/StatusPill";

const COUNT_LABELS: Array<[keyof IncidentDetail["counts"], string]> = [
  ["facts", "Facts"],
  ["evidence", "Evidence"],
  ["hypotheses", "Hypotheses"],
  ["open_questions", "Questions"],
  ["decisions", "Decisions"],
  ["action_items", "Action items"],
  ["timeline_entries", "Timeline"],
  ["mitigation_options", "Mitigations"],
];

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-[var(--border)] py-2 last:border-b-0">
      <dt className="eyebrow">{label}</dt>
      <dd className="min-w-0 truncate text-right text-sm">{children}</dd>
    </div>
  );
}

function When({ iso }: { iso: string | null | undefined }) {
  return <span title={absoluteTime(iso)}>{relativeTime(iso)}</span>;
}

export function IncidentOverview({ incident }: { incident: IncidentDetail }) {
  return (
    <section aria-label="incident overview" className="space-y-5">
      <div className="grid items-start gap-5 lg:grid-cols-[1.4fr_1fr]">
        <Panel title="Current summary">
          <p data-testid="summary-body" className="text-sm leading-6">
            {incident.summary?.body ?? "No summary yet."}
          </p>
          {incident.summary ? (
            <p className="mt-3 text-xs text-[var(--muted)]">
              v{incident.summary.version} · updated{" "}
              <When iso={incident.summary.updated_at} />
            </p>
          ) : null}
        </Panel>

        <Panel title="Details">
          <dl className="m-0">
            <Row label="Status">
              <span data-testid="status">
                <StatusPill status={incident.status} />
              </span>
            </Row>
            <Row label="Agent mode">
              <span data-testid="mode">
                <StatusPill status={incident.mode} />
              </span>
            </Row>
            <Row label="Severity">{incident.severity ?? "—"}</Row>
            <Row label="Source">{describeSource(incident.source) ?? "—"}</Row>
            <Row label="Started">
              <When iso={incident.started_at ?? incident.created_at} />
            </Row>
            <Row label="Detected">
              <When iso={incident.detected_at} />
            </Row>
            <Row label="Mitigated">
              <When iso={incident.mitigated_at} />
            </Row>
            <Row label="Resolved">
              <When iso={incident.resolved_at} />
            </Row>
            <Row label="Slack channel">{incident.slack_channel_id ?? "—"}</Row>
          </dl>
        </Panel>
      </div>

      <div>
        <h2 className="eyebrow mb-2">Recorded memory</h2>
        <ul
          aria-label="counts"
          className="grid list-none grid-cols-[repeat(auto-fit,minmax(130px,1fr))] gap-3 p-0"
        >
          {COUNT_LABELS.map(([key, label]) => (
            <li
              key={key}
              data-testid={`count-${key}`}
              className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3"
            >
              <div className="text-2xl font-semibold tabular-nums">
                {incident.counts[key]}
              </div>
              <div className="mt-0.5 text-xs text-[var(--muted)]">{label}</div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
