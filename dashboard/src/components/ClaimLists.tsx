import type { Evidence, Hypothesis } from "@/lib/api";
import { EmptyState } from "@/components/ui/Panel";
import { StatusPill } from "@/components/ui/StatusPill";

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return <EmptyState>No evidence yet.</EmptyState>;
  return (
    <ul aria-label="evidence" className="m-0 list-none p-0">
      {evidence.map((e) => (
        <li
          key={e.id}
          data-testid="evidence-item"
          className="border-b border-[var(--border)] py-3 last:border-b-0"
        >
          <div className="flex items-start justify-between gap-3">
            <span className="font-medium">{e.title ?? "(untitled)"}</span>
            <StatusPill
              status={e.tool_call_id ? "grounded" : "ungrounded"}
              tone={e.tool_call_id ? "positive" : "warning"}
              title={
                e.tool_call_id
                  ? `Traced to tool call ${e.tool_call_id}`
                  : "No tool call recorded for this observation"
              }
            />
          </div>
          {e.body ? (
            <p className="my-1 text-sm text-[var(--foreground)]/85">{e.body}</p>
          ) : null}
          <div className="text-xs text-[var(--muted)]">
            {e.system ? `${e.system}` : "unknown source"}
            {typeof e.confidence === "number"
              ? ` · confidence ${e.confidence.toFixed(2)}`
              : ""}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function HypothesisList({ hypotheses }: { hypotheses: Hypothesis[] }) {
  if (hypotheses.length === 0)
    return <EmptyState>No hypotheses yet.</EmptyState>;
  const ranked = [...hypotheses].sort(
    (a, b) => (a.rank ?? 999) - (b.rank ?? 999),
  );
  return (
    <ul aria-label="hypotheses" className="m-0 list-none p-0">
      {ranked.map((h) => (
        <li
          key={h.id}
          data-testid="hypothesis-item"
          className="border-b border-[var(--border)] py-3 last:border-b-0"
        >
          <div className="flex items-start justify-between gap-3">
            <span className="font-medium">
              {h.rank != null ? (
                <span className="mr-1.5 text-[var(--muted)] tabular-nums">
                  #{h.rank}
                </span>
              ) : null}
              {h.statement ?? "(no statement)"}
            </span>
            {h.status ? (
              // Hypothesis states are their own vocabulary: an "open"
              // hypothesis is simply unresolved, not an alarm.
              <StatusPill
                status={h.status}
                tone={
                  h.status === "supported"
                    ? "positive"
                    : h.status === "refuted"
                      ? "neutral"
                      : "info"
                }
              />
            ) : null}
          </div>
          <div className="mt-0.5 text-xs text-[var(--muted)]">
            {typeof h.likelihood === "number"
              ? `likelihood ${h.likelihood.toFixed(2)}`
              : "likelihood —"}
          </div>
          {h.supporting_evidence && h.supporting_evidence.length > 0 ? (
            <ul className="mt-1.5 list-disc pl-5 text-sm text-[var(--foreground)]/85">
              {h.supporting_evidence.map((e) => (
                <li key={e.id}>
                  {e.title ?? e.body ?? e.id}
                  {e.system ? (
                    <span className="text-[var(--muted)]"> ({e.system})</span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-xs text-[var(--muted)]">
              No supporting evidence linked
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}
