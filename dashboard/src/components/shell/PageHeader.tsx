"use client";

import Link from "next/link";

import { toneSolid, type Tone } from "@/components/ui/StatusPill";
import { useReadiness } from "@/lib/hooks";

function ReadinessBadge() {
  const { state, label } = useReadiness();
  const tone: Tone =
    state === "ready" ? "positive" : state === "degraded" ? "warning" : "neutral";
  return (
    <span
      data-testid="readiness"
      className="inline-flex items-center gap-2 text-xs text-[var(--muted)]"
    >
      <span
        className="h-2 w-2 rounded-full"
        style={{ background: toneSolid(tone) }}
      />
      {label}
    </span>
  );
}

export function PageHeader({
  title,
  subtitle,
  breadcrumb,
  right,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  breadcrumb?: { label: string; href: string };
  right?: React.ReactNode;
}) {
  return (
    <header className="sticky top-0 z-10 border-b border-[var(--border)] bg-[var(--surface)] px-6 py-3.5">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          {breadcrumb ? (
            <Link
              href={breadcrumb.href}
              className="text-xs text-[var(--muted)] hover:text-[var(--accent)]"
            >
              ← {breadcrumb.label}
            </Link>
          ) : null}
          <h1 className="truncate text-lg font-semibold">{title}</h1>
          {subtitle ? (
            <div className="mt-0.5 text-xs text-[var(--muted)]">{subtitle}</div>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-4">
          {right}
          <ReadinessBadge />
        </div>
      </div>
    </header>
  );
}
