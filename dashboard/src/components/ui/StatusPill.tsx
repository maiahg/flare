export type Tone =
  | "critical"
  | "warning"
  | "info"
  | "positive"
  | "special"
  | "neutral";

/** Filled colour for a mark that is not a chip — chart bar, dot, progress. */
export function toneSolid(tone: Tone): string {
  return `var(--tone-${tone}-solid)`;
}

/**
 * Large-figure colour on white. Distinct from the chip `fg`, which is darkened
 * for contrast against its tinted background and reads muddy at display sizes.
 */
export function toneText(tone: Tone): string {
  return `var(--tone-${tone}-text)`;
}

const STATE_TONE: Record<string, Tone> = {
  // Incident statuses.
  open: "critical",
  mitigating: "warning",
  monitoring: "info",
  resolved: "positive",
  closed: "neutral",
  // Incident modes.
  quiet: "neutral",
  scribe: "info",
  assist: "special",
  active: "warning",
  // Run / tool-call statuses.
  ok: "positive",
  done: "positive",
  running: "info",
  pending: "warning",
  queued: "warning",
  error: "critical",
  failed: "critical",
  refused: "critical",
};

export function toneFor(state: string | null | undefined): Tone {
  return STATE_TONE[(state ?? "").toLowerCase()] ?? "neutral";
}

/** Inline custom properties the `.chip` component class reads. */
export function chipVars(tone: Tone): React.CSSProperties {
  return {
    "--chip-bg": `var(--tone-${tone}-bg)`,
    "--chip-fg": `var(--tone-${tone}-fg)`,
    "--chip-bd": `var(--tone-${tone}-bd)`,
  } as React.CSSProperties;
}

export function StatusPill({
  status,
  tone,
  title,
}: {
  status?: string | null;
  tone?: Tone;
  title?: string;
}) {
  const label = status ?? "pending";
  return (
    <span
      data-testid="status-pill"
      title={title}
      className="chip"
      style={chipVars(tone ?? toneFor(label))}
    >
      {label}
    </span>
  );
}
