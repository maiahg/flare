import type { Postmortem } from "@/lib/api";
import { EmptyState } from "@/components/ui/Panel";
import { StatusPill } from "@/components/ui/StatusPill";
import { absoluteTime } from "@/lib/format";

type Entry = { text?: string; at?: string | null; entry_type?: string | null };
type Sections = Record<string, unknown>;

const ENTRY_TYPE_LABELS: Record<string, string> = {
  deploy: "Deploy",
  mitigation: "Mitigation",
  observation: "Observation",
};

function asEntries(value: unknown): Entry[] {
  return Array.isArray(value) ? (value as Entry[]) : [];
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function EntryList({ entries, label }: { entries: Entry[]; label: string }) {
  const shown = entries.filter((e) => asString(e.text));
  if (shown.length === 0)
    return <EmptyState>Nothing recorded for {label.toLowerCase()}.</EmptyState>;
  return (
    <ul aria-label={label} className="m-0 list-none space-y-2.5 p-0">
      {shown.map((e, i) => (
        <li key={i} className="text-sm">
          <p className="text-[var(--foreground)]/90">
            {e.at ? (
              <span className="mr-1.5 text-[var(--muted)] tabular-nums">
                {e.at}
              </span>
            ) : null}
            {e.text}
          </p>
        </li>
      ))}
    </ul>
  );
}

function TimelineList({ entries }: { entries: Entry[] }) {
  const shown = entries.filter((e) => asString(e.text));
  if (shown.length === 0)
    return <EmptyState>Nothing recorded for timeline.</EmptyState>;
  return (
    <ol aria-label="Timeline" className="m-0 list-none space-y-2.5 p-0">
      {shown.map((e, i) => {
        const type = asString(e.entry_type);
        return (
          <li key={i} className="flex gap-2.5 text-sm">
            <span className="w-36 shrink-0 text-[var(--muted)] tabular-nums">
              {e.at ? absoluteTime(e.at) : "time unknown"}
            </span>
            <p className="text-[var(--foreground)]/90">
              {type ? (
                <span className="mr-1.5 rounded bg-[var(--border)] px-1.5 py-0.5 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">
                  {ENTRY_TYPE_LABELS[type] ?? type}
                </span>
              ) : null}
              {e.text}
            </p>
          </li>
        );
      })}
    </ol>
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
    <section className="border-b border-[var(--border)] pb-5 last:border-b-0">
      <h3 className="eyebrow mb-2 text-[var(--muted)]">{title}</h3>
      {children}
    </section>
  );
}

function RootCause({ value }: { value: unknown }) {
  if (!value || typeof value !== "object")
    return (
      <EmptyState>
        Root cause undetermined — no supported hypothesis in memory.
      </EmptyState>
    );
  const rc = value as Record<string, unknown>;
  return (
    <div className="text-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium text-[var(--foreground)]">
          {asString(rc.statement) ?? "(no statement)"}
        </p>
        {asString(rc.status) ? <StatusPill status={String(rc.status)} /> : null}
      </div>
    </div>
  );
}

export function PostmortemView({ postmortem }: { postmortem: Postmortem | null }) {
  if (!postmortem) {
    return (
      <EmptyState>
        No postmortem yet. Run <code>@flare postmortem</code> in the incident
        channel to draft one from memory.
      </EmptyState>
    );
  }
  const sections = (postmortem.sections ?? {}) as Sections;
  const followUps = postmortem.follow_ups;
  const actionItems = Array.isArray(followUps)
    ? asEntries(followUps)
    : followUps && typeof followUps === "object"
      ? asEntries((followUps as Record<string, unknown>).action_items)
      : [];
  const limitations = Array.isArray(sections.limitations)
    ? (sections.limitations as unknown[]).map(String)
    : [];
  const provenance = (sections.provenance ?? {}) as Record<string, unknown>;
  const degraded = Boolean(provenance.degraded);
  const summary = sections.summary as Entry | null | undefined;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={String(sections.status ?? postmortem.version)} />
        {asString(sections.severity) ? (
          <span className="text-sm text-[var(--muted)]">
            {String(sections.severity)}
          </span>
        ) : null}
        <span className="text-sm text-[var(--muted)]">
          draft v{postmortem.version} · generated{" "}
          {absoluteTime(postmortem.created_at)}
        </span>
      </div>

      {degraded ? (
        <p className="rounded-md border border-[var(--warning,#b45309)]/40 bg-[var(--warning,#b45309)]/10 px-3 py-2 text-sm text-[var(--foreground)]/90">
          ⚠️ Written without the model — sections are assembled from memory only.
        </p>
      ) : null}

      {summary?.text ? (
        <Section title="Summary">
          <p className="text-sm text-[var(--foreground)]/90">{summary.text}</p>
        </Section>
      ) : null}

      <Section title="Root cause">
        <RootCause value={sections.root_cause} />
      </Section>

      <Section title="Impact">
        <EntryList entries={asEntries(sections.impact)} label="Impact" />
      </Section>

      <Section title="Contributing factors">
        <EntryList
          entries={asEntries(sections.contributing_factors)}
          label="Contributing factors"
        />
      </Section>

      <Section title="Timeline">
        <TimelineList entries={asEntries(sections.timeline)} />
      </Section>

      <Section title="What we know">
        <EntryList
          entries={asEntries(sections.what_we_know)}
          label="What we know"
        />
      </Section>

      <Section title="Decisions">
        <EntryList entries={asEntries(sections.decisions)} label="Decisions" />
      </Section>

      <Section title="Follow-up action items">
        <EntryList entries={actionItems} label="Action items" />
      </Section>

      {limitations.length > 0 ? (
        <Section title="Limitations">
          <ul className="m-0 list-disc space-y-1 pl-5 text-sm text-[var(--muted)]">
            {limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}
