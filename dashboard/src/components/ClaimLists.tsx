import type { Evidence, Hypothesis } from "@/lib/api";

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return <p>No evidence yet.</p>;
  return (
    <ul aria-label="evidence" style={{ padding: 0, margin: 0 }}>
      {evidence.map((e) => (
        <li
          key={e.id}
          data-testid="evidence-item"
          style={{ listStyle: "none", marginBottom: "0.75rem" }}
        >
          <div style={{ fontWeight: 600 }}>{e.title ?? "(untitled)"}</div>
          {e.body ? (
            <p style={{ margin: "0.15rem 0", opacity: 0.85 }}>{e.body}</p>
          ) : null}
          <div style={{ fontSize: "0.78rem", opacity: 0.6 }}>
            {e.system ? `${e.system}` : "unknown source"}
            {typeof e.confidence === "number"
              ? ` · confidence ${e.confidence.toFixed(2)}`
              : ""}
            {e.tool_call_id ? " · grounded ✓" : " · ungrounded ⚠"}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function HypothesisList({
  hypotheses,
}: {
  hypotheses: Hypothesis[];
}) {
  if (hypotheses.length === 0) return <p>No hypotheses yet.</p>;
  const ranked = [...hypotheses].sort(
    (a, b) => (a.rank ?? 999) - (b.rank ?? 999),
  );
  return (
    <ul aria-label="hypotheses" style={{ padding: 0, margin: 0 }}>
      {ranked.map((h) => (
        <li
          key={h.id}
          data-testid="hypothesis-item"
          style={{ listStyle: "none", marginBottom: "1rem" }}
        >
          <div style={{ fontWeight: 600 }}>
            {h.rank != null ? `#${h.rank} ` : ""}
            {h.statement ?? "(no statement)"}
          </div>
          <div style={{ fontSize: "0.8rem", opacity: 0.6 }}>
            {typeof h.likelihood === "number"
              ? `likelihood ${h.likelihood.toFixed(2)}`
              : "likelihood —"}
            {h.status ? ` · ${h.status}` : ""}
          </div>
          {h.supporting_evidence && h.supporting_evidence.length > 0 ? (
            <ul style={{ margin: "0.35rem 0 0", paddingLeft: "1rem" }}>
              {h.supporting_evidence.map((e) => (
                <li key={e.id} style={{ fontSize: "0.82rem", opacity: 0.85 }}>
                  {e.title ?? e.body ?? e.id}
                  {e.system ? ` (${e.system})` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p style={{ margin: "0.25rem 0 0", opacity: 0.5, fontSize: "0.8rem" }}>
              No supporting evidence linked
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}