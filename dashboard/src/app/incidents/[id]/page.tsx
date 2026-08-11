"use client";

import { Suspense, use, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { EvidenceList, HypothesisList } from "@/components/ClaimLists";
import { IncidentOverview } from "@/components/IncidentOverview";
import { RunDetailView, RunList } from "@/components/RunTrace";
import { PageHeader } from "@/components/shell/PageHeader";
import { INCIDENT_TABS, type IncidentTab } from "@/components/shell/Sidebar";
import { TokenUsagePanel } from "@/components/TokenUsage";
import { Timeline } from "@/components/Timeline";
import { EmptyState, Panel } from "@/components/ui/Panel";
import { StatusPill } from "@/components/ui/StatusPill";
import { relativeTime } from "@/lib/format";
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

const TAB_KEYS = INCIDENT_TABS.map(([key]) => key) as readonly string[];

export default function IncidentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <Suspense fallback={<PageHeader title="Incident" />}>
      <IncidentView id={id} />
    </Suspense>
  );
}

function IncidentView({ id }: { id: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requested = searchParams.get("tab") ?? "overview";
  const tab = (TAB_KEYS.includes(requested) ? requested : "overview") as IncidentTab;

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

  const setTab = (next: IncidentTab) => {
    router.replace(next === "overview" ? pathname : `${pathname}?tab=${next}`, {
      scroll: false,
    });
  };

  const data = incident.data;

  return (
    <>
      <PageHeader
        breadcrumb={{ label: "Incidents", href: "/incidents" }}
        title={data?.title ?? "Incident"}
        subtitle={
          data ? (
            <span className="flex flex-wrap items-center gap-2">
              <StatusPill status={data.status} />
              <StatusPill status={data.mode} title="Agent mode" />
              {data.severity ? <span>{data.severity}</span> : null}
              <span>
                started {relativeTime(data.started_at ?? data.created_at)}
              </span>
            </span>
          ) : null
        }
      />

      <div className="border-b border-[var(--border)] bg-[var(--surface)] px-6">
        <nav aria-label="incident views" className="flex gap-1 overflow-x-auto">
          {INCIDENT_TABS.map(([key, label, Icon]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              aria-current={tab === key ? "page" : undefined}
              className={`-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition-colors ${
                tab === key
                  ? "border-[var(--accent)] font-medium text-[var(--accent)]"
                  : "border-transparent text-[var(--muted)] hover:text-[var(--foreground)]"
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </nav>
      </div>

      <div className="px-6 py-5">
        {incident.isLoading ? <EmptyState>Loading incident…</EmptyState> : null}
        {incident.isError ? (
          <EmptyState>
            Failed to load incident.{" "}
            <Link href="/incidents" className="text-[var(--accent)] hover:underline">
              Back to incidents
            </Link>
          </EmptyState>
        ) : null}

        {tab === "overview" && data ? <IncidentOverview incident={data} /> : null}

        {tab === "timeline" ? (
          <Panel title="Timeline">
            <Timeline entries={timeline.data ?? []} />
          </Panel>
        ) : null}

        {tab === "runs" ? (
          <div className="grid items-start gap-5 lg:grid-cols-[280px_1fr]">
            <Panel title="Runs" bodyClassName="p-2">
              <RunList
                runs={runs.data ?? []}
                selectedId={selectedRun}
                onSelect={setSelectedRun}
              />
            </Panel>
            <Panel title="Run trace">
              {run.isLoading ? <EmptyState>Loading run…</EmptyState> : null}
              {run.data ? <RunDetailView run={run.data} /> : null}
              {!run.isLoading && !run.data ? (
                <EmptyState>Select a run to see its agent trace.</EmptyState>
              ) : null}
            </Panel>
          </div>
        ) : null}

        {tab === "evidence" ? (
          <Panel title="Evidence">
            <EvidenceList evidence={evidence.data ?? []} />
          </Panel>
        ) : null}

        {tab === "hypotheses" ? (
          <Panel title="Hypotheses">
            <HypothesisList hypotheses={hypotheses.data ?? []} />
          </Panel>
        ) : null}

        {tab === "usage" ? (
          <Panel title="Token usage">
            {usage.isLoading ? <EmptyState>Loading usage…</EmptyState> : null}
            {usage.data ? <TokenUsagePanel usage={usage.data} /> : null}
          </Panel>
        ) : null}
      </div>
    </>
  );
}
