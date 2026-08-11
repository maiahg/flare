import Link from "next/link";

import { toneText, type Tone } from "./StatusPill";
import { ArrowRightIcon } from "./icons";

export function StatCard({
  label,
  value,
  icon,
  tone,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  icon?: React.ReactNode;
  /** Colours the figure. Omit for plain ink — a count is not a status. */
  tone?: Tone;
  hint?: string;
}) {
  return (
    <div
      data-testid={`stat-${label.toLowerCase().replace(/\s+/g, "-")}`}
      title={hint}
      className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3.5 shadow-[var(--shadow-card)]"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="eyebrow">{label}</span>
        <span className="text-[var(--faint)]">{icon}</span>
      </div>
      <div
        className="mt-2 text-[1.75rem] font-semibold leading-tight tracking-[-0.02em] tabular-nums"
        style={tone ? { color: toneText(tone) } : undefined}
      >
        {value}
      </div>
    </div>
  );
}

export function StatGroup({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="min-w-0">
      <h2 className="eyebrow mb-2">{title}</h2>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
        {children}
      </div>
    </section>
  );
}

export function Panel({
  title,
  action,
  children,
  className = "",
  bodyClassName = "p-4",
}: {
  title: string;
  action?: { label: string; href: string };
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      aria-label={title}
      className={`overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-card)] ${className}`}
    >
      <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <h2 className="text-[0.95rem] font-semibold">{title}</h2>
        {action ? (
          <Link
            href={action.href}
            className="inline-flex items-center gap-1 text-xs font-medium text-[var(--accent)] hover:underline"
          >
            {action.label}
            <ArrowRightIcon className="h-3.5 w-3.5" />
          </Link>
        ) : null}
      </header>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-1 py-6 text-center text-sm text-[var(--muted)]">
      {children}
    </p>
  );
}
