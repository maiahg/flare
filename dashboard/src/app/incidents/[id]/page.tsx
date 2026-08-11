"use client";

import { use, useEffect, useState } from "react";

import { EvidenceList, HypothesisList } from "@/components/ClaimLists";
import { IncidentOverview } from "@/components/IncidentOverview";
import { RunDetailView, RunList } from "@/components/RunTrace";
import { TokenUsagePanel } from "@/components/TokenUsage";
import { Timeline } from "@/components/Timeline";
import {
  useEvidence,
  useHypotheses,
  useIncident,
  useRun,
  useRuns,
  useTimeline,
  useUsage,
} from "@/lib/hooks";
import { useIncidentStream } from "@/lib/useIncidentStream";

type Tab =
  | "overview"
  | "timeline"
  | "runs"
  | "evidence"
  | "hypotheses"
  | "usage";

const TABS: Array<[Tab, string]> = [
  ["overview", "Overview"],
  ["timeline", "Timeline"],
  ["runs", "Runs"],
  ["evidence", "Evidence"],
  ["hypotheses", "Hypotheses"],
  ["usage", "Tokens"],
];

export default function IncidentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [tab, setTab] = useState<Tab>("overview");
  const [selectedRun, setSelectedRun] = useState<string | null>(null);

  // Live: invalidate this incident's queries whenever memory changes.
  useIncidentStream(id);

  const incident = useIncident(id);
  const timeline = useTimeline(id);
  const runs = useRuns(id);
  const run = useRun(id, selectedRun);
  const evidence = useEvidence(id);
  const hypotheses = useHypotheses(id);
  const usage = useUsage(id);

  // Default to the most recent run once the list loads.
  useEffect(() => {
    if (!selectedRun && runs.data && runs.data.length > 0) {
      setSelectedRun(runs.data[0].id);
    }
  }, [runs.data, selectedRun]);

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <nav style={{ display: "flex", gap: "1rem", marginBottom: "1.5rem" }}>
        {TABS.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            disabled={tab === key}
          >
            {label}
          </button>
        ))}
      </nav>

      {incident.isLoading ? <p>Loading…</p> : null}
      {incident.isError ? <p>Failed to load incident.</p> : null}

      {tab === "overview" && incident.data ? (
        <IncidentOverview incident={incident.data} />
      ) : null}

      {tab === "timeline" ? (
        <Timeline entries={timeline.data ?? []} />
      ) : null}

      {tab === "runs" ? (
        <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: "1.5rem" }}>
          <RunList
            runs={runs.data ?? []}
            selectedId={selectedRun}
            onSelect={setSelectedRun}
          />
          <div>
            {run.isLoading ? <p>Loading run…</p> : null}
            {run.data ? <RunDetailView run={run.data} /> : null}
          </div>
        </div>
      ) : null}

      {tab === "evidence" ? (
        <EvidenceList evidence={evidence.data ?? []} />
      ) : null}

      {tab === "hypotheses" ? (
        <HypothesisList hypotheses={hypotheses.data ?? []} />
      ) : null}

      {tab === "usage" ? (
        <>
          {usage.isLoading ? <p>Loading usage…</p> : null}
          {usage.data ? <TokenUsagePanel usage={usage.data} /> : null}
        </>
      ) : null}
      
    </main>
  );
}