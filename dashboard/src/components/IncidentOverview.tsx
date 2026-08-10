import type { IncidentDetail } from "@/lib/api";

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

export function IncidentOverview({ incident }: { incident: IncidentDetail }) {
  return (
    <section aria-label="incident overview">
      <header style={{ marginBottom: "1rem" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>{incident.title}</h1>
        <p style={{ opacity: 0.7 }}>
          <span data-testid="status">{incident.status}</span>
          {incident.severity ? ` · ${incident.severity}` : ""}
          {" · "}
          <span data-testid="mode">{incident.mode}</span>
        </p>
      </header>

      <div aria-label="summary" style={{ marginBottom: "1rem" }}>
        <h2 style={{ fontSize: "1rem", fontWeight: 600 }}>Summary</h2>
        <p data-testid="summary-body">
          {incident.summary?.body ?? "No summary yet."}
        </p>
      </div>

      <ul
        aria-label="counts"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: "0.5rem",
          listStyle: "none",
          padding: 0,
        }}
      >
        {COUNT_LABELS.map(([key, label]) => (
          <li key={key} data-testid={`count-${key}`}>
            <strong>{incident.counts[key]}</strong> <span>{label}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}