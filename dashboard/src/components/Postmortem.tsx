import type { Postmortem } from "@/lib/api";
import { EmptyState } from "@/components/ui/Panel";
import { StatusPill } from "@/components/ui/StatusPill";
import { absoluteTime } from "@/lib/format";

type Citation = Record<string, unknown>;
type Entry = { text?: string; provenance?: Citation[]; at?: string | null };
type Sections = Record<string, unknown>;

function asEntries(value: unknown): Entry[] {
  return Array.isArray(value) ? (value as Entry[]) : [];
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function citationLabel(c: Citation): string {
  if (c.kind === "evidence") {
    const system = asString(c.system);
    const title = asString(c.title);
    return [system ? `[${system}]` : null, title ?? "evidence"]
      .filter(Boolean)
      .join(" ");
  }
  const entity = asString(c.entity_type) ?? "memory";
  const author = asString(c.created_by);
  return author ? `${entity} · ${author}` : entity;
}

function Citations({ items }: { items?: Citation[] }) {
  if (!items || items.length === 0) {
    return (
      <span className="text-xs text-[var(--warning,#b45309)]">uncited</span>
    );
  }
  return (
    <span className="flex flex-wrap gap-1.5">
      {items.map((c, i) => (
        <span
          key={i}
          className="inline-flex items-center rounded border border-[var(--border)] bg-[var(--surface-muted,var(--surface))] px-1.5 py-0.5 text-[0.7rem] text-[var(--muted)]"
          title={c.kind === "evidence" && c.tool_call_id ? `tool call ${String(c.tool_call_id)}` : undefined}
        >
          {citationLabel(c)}
          {c.stale ? " · stale" : ""}
        </span>
      ))}
    </span>
  );
}

function EntryList({ entries, label }: { entries: Entry[]; label: string }) {
  if (entries.length === 0)
    return <EmptyState>Nothing recorded for {label.toLowerCase()}.</EmptyState>;
  return (
    <ul aria-label={label} className="m-0 list-none space-y-2.5 p-0">
      {entries.map((e, i) => (
        <li key={i} className="text-sm">
          <p className="text-[var(--foreground)]/90">
            {e.at ? (
              <span className="mr-1.5 text-[var(--muted)] tabular-nums">
                {e.at}
              </span>
            ) : null}
            {e.text ?? "(no text)"}
          </p>
          <div className="mt-1">
            <Citations items={e.provenance} />
          </div>
        </li>
      ))}
    </ul>
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
  const provenance = Array.isArray(rc.provenance)
    ? (rc.provenance as Citation[])
    : [];
  const contradicted = Array.isArray(rc.contradicted_by)
    ? (rc.contradicted_by as Citation[])
    : [];
  return (
    <div className="text-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium text-[var(--foreground)]">
          {asString(rc.statement) ?? "(no statement)"}
        </p>
        {asString(rc.status) ? <StatusPill status={String(rc.status)} /> : null}
      </div>
      <div className="mt-2">
        <p className="mb-1 text-xs text-[var(--muted)]">Supported by</p>
        <Citations items={provenance} />
      </div>
      {contradicted.length > 0 ? (
        <div className="mt-2">
          <p className="mb-1 text-xs text-[var(--muted)]">Contradicted by</p>
          <Citations items={contradicted} />
        </div>
      ) : null}
    </div>
  );
}

export function PostmortemView({ postmortem }: { postmortem: Postmortem | null }) {
  if (!postmortem) {
    return (
      <EmptyState>
        No postmortem yet. Run <code>/flare postmortem</code> in the incident
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
          <div className="mt-1">
            <Citations items={summary.provenance} />
          </div>
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
        <EntryList entries={asEntries(sections.timeline)} label="Timeline" />
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
