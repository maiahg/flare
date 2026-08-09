"use client";

import { use, useState } from "react";

import { IncidentOverview } from "@/components/IncidentOverview";
import { Timeline } from "@/components/Timeline";
import { useIncident, useTimeline } from "@/lib/hooks";
import { useIncidentStream } from "@/lib/useIncidentStream";

type Tab = "overview" | "timeline";

export default function IncidentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [tab, setTab] = useState<Tab>("overview");

  useIncidentStream(id);

  const incident = useIncident(id);
  const timeline = useTimeline(id);

  return (
    <main style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1rem" }}>
      <nav style={{ display: "flex", gap: "1rem", marginBottom: "1.5rem" }}>
        <button onClick={() => setTab("overview")} disabled={tab === "overview"}>
          Overview
        </button>
        <button onClick={() => setTab("timeline")} disabled={tab === "timeline"}>
          Timeline
        </button>
      </nav>

      {incident.isLoading ? <p>Loading…</p> : null}
      {incident.isError ? <p>Failed to load incident.</p> : null}

      {tab === "overview" && incident.data ? (
        <IncidentOverview incident={incident.data} />
      ) : null}

      {tab === "timeline" ? (
        <Timeline entries={timeline.data ?? []} />
      ) : null}
    </main>
  );
}