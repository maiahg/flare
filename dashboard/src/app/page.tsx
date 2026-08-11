"use client";

import Link from "next/link";

import { IncidentTable } from "@/components/IncidentTable";
import { PageHeader } from "@/components/shell/PageHeader";
import { BarChart } from "@/components/ui/BarChart";
import { EmptyState, Panel, StatCard, StatGroup } from "@/components/ui/Panel";
import {
  AlertIcon,
  ActivityIcon,
  ClockIcon,
  EvidenceIcon,
  ShieldIcon,
  SparkIcon,
} from "@/components/ui/icons";
import { toneFor, toneSolid } from "@/components/ui/StatusPill";
import type { Incident } from "@/lib/api";
import { useIncidents } from "@/lib/hooks";

/** Chart order, left to right: least to most agent autonomy. */
const MODES = ["quiet", "scribe", "assist", "active"] as const;

function countBy(incidents: Incident[], field: "status" | "mode") {
  const counts: Record<string, number> = {};
  for (const incident of incidents) {
    const key = incident[field] ?? "unknown";
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}

export default function DashboardPage() {
  const { data, isLoading, isError } = useIncidents();
  const incidents = data ?? [];
  const byStatus = countBy(incidents, "status");
  const byMode = countBy(incidents, "mode");
  const at = (counts: Record<string, number>, ...keys: string[]) =>
    keys.reduce((sum, key) => sum + (counts[key] ?? 0), 0);

  return (
    <>
      <PageHeader title="Dashboard" />

      <div className="space-y-5 px-6 py-5">
        <div className="grid gap-5 xl:grid-cols-[1.25fr_1fr]">
          <StatGroup title="Incidents">
            <StatCard
              label="Open"
              value={at(byStatus, "open")}
              icon={<AlertIcon />}
              tone={toneFor("open")}
            />
            <StatCard
              label="Mitigating"
              value={at(byStatus, "mitigating")}
              icon={<ShieldIcon />}
              tone={toneFor("mitigating")}
            />
            <StatCard
              label="Monitoring"
              value={at(byStatus, "monitoring")}
              icon={<ActivityIcon />}
              tone={toneFor("monitoring")}
            />
            <StatCard
              label="Resolved"
              value={at(byStatus, "resolved", "closed")}
              icon={<EvidenceIcon />}
              tone={toneFor("resolved")}
              hint="Resolved and closed incidents"
            />
          </StatGroup>

          <StatGroup title="AI agent">
            <StatCard
              label="Acting"
              value={at(byMode, "active")}
              icon={<SparkIcon />}
              hint="Incidents in active mode: the agent may propose and, once approved, run mitigations"
            />
            <StatCard
              label="Assisting"
              value={at(byMode, "assist")}
              icon={<ActivityIcon />}
              hint="Assist mode: the agent investigates and answers, but takes no action"
            />
            <StatCard
              label="Observing"
              value={at(byMode, "quiet", "scribe")}
              icon={<ClockIcon />}
              hint="Quiet and scribe modes: recording only"
            />
          </StatGroup>
        </div>

        <div className="grid items-start gap-5 xl:grid-cols-[1.25fr_1fr]">
          <Panel
            title="Recent incidents"
            action={{ label: "View all", href: "/incidents" }}
            bodyClassName=""
          >
            {isLoading ? (
              <EmptyState>Loading incidents…</EmptyState>
            ) : isError ? (
              <EmptyState>Failed to load incidents.</EmptyState>
            ) : (
              <IncidentTable incidents={incidents.slice(0, 8)} />
            )}
          </Panel>

          <Panel title="Agent engagement">
            <p className="mb-3 text-xs text-[var(--muted)]">
              Incidents by the mode the copilot is running in. Mode is per
              incident and decides how far the agent may go on its own.
            </p>
            <BarChart
              ariaLabel="incidents by agent mode"
              // Bar colour comes from the same tone map as the mode pills in
              // the table beside it, so the two can never disagree.
              bars={MODES.map((mode) => ({
                label: mode,
                value: byMode[mode] ?? 0,
                color: toneSolid(toneFor(mode)),
              }))}
            />
            <p className="mt-3 text-xs text-[var(--muted)]">
              {incidents.length} incident{incidents.length === 1 ? "" : "s"}{" "}
              tracked ·{" "}
              <Link href="/incidents" className="text-[var(--accent)] hover:underline">
                manage
              </Link>
            </p>
          </Panel>
        </div>
      </div>
    </>
  );
}
