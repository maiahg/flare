"use client";

import { useState } from "react";

import { IncidentTable } from "@/components/IncidentTable";
import { PageHeader } from "@/components/shell/PageHeader";
import { EmptyState, Panel } from "@/components/ui/Panel";
import { useIncidents } from "@/lib/hooks";

const FILTERS = [
  ["", "All"],
  ["open", "Open"],
  ["mitigating", "Mitigating"],
  ["monitoring", "Monitoring"],
  ["resolved", "Resolved"],
  ["closed", "Closed"],
] as const;

export default function IncidentsPage() {
  const [status, setStatus] = useState("");
  const { data, isLoading, isError } = useIncidents(status || undefined);
  const incidents = data ?? [];

  return (
    <>
      <PageHeader
        title="Incidents"
        subtitle={`${incidents.length} incident${
          incidents.length === 1 ? "" : "s"
        }${status ? ` in ${status}` : ""}`}
      />

      <div className="px-6 py-5">
        <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="status filter">
          {FILTERS.map(([value, label]) => (
            <button
              key={value || "all"}
              onClick={() => setStatus(value)}
              aria-pressed={status === value}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                status === value
                  ? "border-[var(--accent)] bg-[var(--accent)] text-white"
                  : "border-[var(--border)] bg-[var(--surface)] text-[var(--muted)] hover:border-[var(--border-strong)] hover:text-[var(--foreground)]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <Panel title="All incidents" bodyClassName="">
          {isLoading ? (
            <EmptyState>Loading incidents…</EmptyState>
          ) : isError ? (
            <EmptyState>Failed to load incidents.</EmptyState>
          ) : (
            <IncidentTable incidents={incidents} />
          )}
        </Panel>
      </div>
    </>
  );
}
