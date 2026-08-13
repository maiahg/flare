"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import { useReadiness } from "@/lib/hooks";
import {
  ActivityIcon,
  AlertIcon,
  BulbIcon,
  DocumentIcon,
  EvidenceIcon,
  GridIcon,
  RunsIcon,
  SparkIcon,
  TokenIcon,
} from "@/components/ui/icons";

export const INCIDENT_TABS = [
  ["overview", "Overview", ActivityIcon],
  ["runs", "Runs", RunsIcon],
  ["evidence", "Evidence", EvidenceIcon],
  ["hypotheses", "Hypotheses", BulbIcon],
  ["postmortem", "Postmortem", DocumentIcon],
  ["usage", "Tokens", TokenIcon],
] as const;

export type IncidentTab = (typeof INCIDENT_TABS)[number][0];

function NavItem({
  href,
  label,
  icon: Icon,
  active,
}: {
  href: string;
  label: string;
  icon: (p: { className?: string }) => React.ReactElement;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-2.5 rounded-md border-l-2 px-3 py-2 text-[0.83rem] transition-colors ${
        active
          ? "border-[var(--accent)] bg-[var(--sidebar-active)] font-medium text-white"
          : "border-transparent text-[var(--sidebar-muted)] hover:bg-[var(--sidebar-hover)] hover:text-[var(--sidebar-fg)]"
      }`}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="truncate">{label}</span>
    </Link>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-5">
      <p className="eyebrow px-3 pb-1.5 text-[var(--sidebar-faint)]">{title}</p>
      <nav className="flex flex-col gap-0.5">{children}</nav>
    </div>
  );
}

export function Sidebar() {
  const pathname = usePathname() ?? "/";
  const params = useSearchParams();
  const readiness = useReadiness();

  const incidentMatch = /^\/incidents\/([^/]+)/.exec(pathname);
  const incidentId = incidentMatch?.[1];
  const currentTab = params.get("tab") ?? "overview";

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col bg-[var(--sidebar)] py-4">
      <div className="mb-6 flex items-center gap-2 px-4">
        <span className="grid h-6 w-6 place-items-center rounded bg-[var(--accent)] text-white">
          <SparkIcon className="h-3.5 w-3.5" />
        </span>
        <span className="text-[0.72rem] font-semibold tracking-[0.12em] text-[var(--sidebar-fg)]">
          FLARE
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-2">
        <Section title="Overview">
          <NavItem
            href="/"
            label="Dashboard"
            icon={GridIcon}
            active={pathname === "/"}
          />
        </Section>

        <Section title="Incidents">
          <NavItem
            href="/incidents"
            label="All incidents"
            icon={AlertIcon}
            // Exact match: an open incident lights up its own section below,
            // and two highlighted items would make neither mean anything.
            active={pathname === "/incidents"}
          />
        </Section>

        {incidentId ? (
          <Section title="Current incident">
            {INCIDENT_TABS.map(([tab, label, icon]) => (
              <NavItem
                key={tab}
                href={`/incidents/${incidentId}?tab=${tab}`}
                label={label}
                icon={icon}
                active={currentTab === tab}
              />
            ))}
          </Section>
        ) : null}
      </div>

      <div className="mt-2 border-t border-[var(--sidebar-border)] px-4 pt-3 text-[0.7rem] text-[var(--sidebar-faint)]">
        <p className="mb-0.5 uppercase tracking-[0.09em]">Backend</p>
        <p data-testid="sidebar-readiness">
          db {readiness.checks.database ? "ok" : "down"} · redis{" "}
          {readiness.checks.redis ? "ok" : "down"}
        </p>
      </div>
    </aside>
  );
}
