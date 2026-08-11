import type { AgentTrace, Run, RunDetail, ToolCall } from "@/lib/api";
import { EmptyState } from "@/components/ui/Panel";
import { StatusPill } from "@/components/ui/StatusPill";
import { NUMBER, absoluteTime, relativeTime } from "@/lib/format";

function tokenSummary(tokens: AgentTrace["tokens"]): string | null {
  if (!tokens) return null;
  const asNum = (v: unknown) => (typeof v === "number" ? v : 0);
  const tin = asNum(tokens["in"]);
  const tout = asNum(tokens["out"]);
  const calls = asNum(tokens["calls"]);
  if (tin === 0 && tout === 0 && calls === 0) return null;
  return `${NUMBER.format(tin)} in / ${NUMBER.format(tout)} out · ${calls} call${
    calls === 1 ? "" : "s"
  }`;
}

function ToolCallRow({ call }: { call: ToolCall }) {
  return (
    <li className="flex list-none flex-wrap items-center gap-x-2 gap-y-1 py-1">
      <code className="rounded bg-[var(--tone-neutral-bg)] px-1.5 py-0.5 text-xs text-[var(--tone-neutral-fg)]">
        {call.tool_name}
      </code>
      {call.system ? (
        <span className="text-xs text-[var(--muted)]">{call.system}</span>
      ) : null}
      {typeof call.latency_ms === "number" ? (
        <span className="text-xs tabular-nums text-[var(--muted)]">
          {call.latency_ms}ms
        </span>
      ) : null}
      <StatusPill status={call.status} />
      {call.error ? (
        <span className="text-xs text-[var(--tone-critical-fg)]">{call.error}</span>
      ) : null}
    </li>
  );
}

function AgentTraceRow({ trace }: { trace: AgentTrace }) {
  const tokens = tokenSummary(trace.tokens);
  return (
    <li
      data-testid="agent-trace"
      className="list-none border-l-2 border-[var(--border)] pl-3.5 pb-4 last:pb-0"
    >
      <div className="flex items-center gap-2">
        <span className="font-medium">
          {trace.seq != null ? (
            <span className="mr-1 text-[var(--muted)] tabular-nums">
              {trace.seq}.
            </span>
          ) : null}
          {trace.agent_name}
        </span>
        <StatusPill status={trace.status} />
      </div>
      {trace.model_name || tokens ? (
        <div data-testid="trace-usage" className="text-xs text-[var(--muted)]">
          {trace.model_name ?? "—"}
          {tokens ? ` · ${tokens}` : ""}
        </div>
      ) : null}
      {trace.reasoning_summary ? (
        <p className="my-1 text-sm text-[var(--foreground)]/85">{trace.reasoning_summary}</p>
      ) : null}
      {trace.tool_calls && trace.tool_calls.length > 0 ? (
        <ul className="m-0 mt-1 p-0">
          {trace.tool_calls.map((c) => (
            <ToolCallRow key={c.id} call={c} />
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-xs text-[var(--muted)]">No tool calls</p>
      )}
    </li>
  );
}

export function RunList({
  runs,
  selectedId,
  onSelect,
}: {
  runs: Run[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (runs.length === 0) return <EmptyState>No runs yet.</EmptyState>;
  return (
    <ul aria-label="runs" className="m-0 list-none p-0">
      {runs.map((r) => {
        const selected = r.id === selectedId;
        return (
          <li key={r.id}>
            <button
              onClick={() => onSelect(r.id)}
              aria-current={selected ? "true" : undefined}
              className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                selected
                  ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                  : "border-transparent hover:bg-[var(--surface-muted)]"
              }`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium">
                  {r.run_type}
                </span>
                <StatusPill status={r.status} />
              </span>
              <span
                className="mt-0.5 block text-xs text-[var(--muted)]"
                title={absoluteTime(r.created_at)}
              >
                {relativeTime(r.created_at)}
                {r.trigger ? ` · ${r.trigger}` : ""}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function RunDetailView({ run }: { run: RunDetail }) {
  const traces = [...(run.agent_traces ?? [])].sort(
    (a, b) => (a.seq ?? 0) - (b.seq ?? 0),
  );
  return (
    <section aria-label="run detail">
      <header className="mb-4">
        <div className="flex items-center gap-2">
          <h3 className="text-[0.95rem] font-semibold">{run.run_type} run</h3>
          <StatusPill status={run.status} />
        </div>
        {run.summary ? (
          <p className="mt-1 text-sm text-[var(--foreground)]/85">{run.summary}</p>
        ) : null}
        {run.token_in != null || run.token_out != null ? (
          <p data-testid="run-tokens" className="mt-1 text-xs text-[var(--muted)]">
            Total tokens: {NUMBER.format(run.token_in ?? 0)} in /{" "}
            {NUMBER.format(run.token_out ?? 0)} out
          </p>
        ) : null}
        {run.limitations && run.limitations.length > 0 ? (
          <p className="mt-2 rounded-md bg-[var(--tone-warning-bg)] px-3 py-2 text-xs text-[var(--tone-warning-fg)] ring-1 ring-inset ring-[var(--tone-warning-bd)]">
            Limitations: {run.limitations.join("; ")}
          </p>
        ) : null}
      </header>
      <ul className="m-0 p-0">
        {traces.map((t) => (
          <AgentTraceRow key={t.id} trace={t} />
        ))}
      </ul>
    </section>
  );
}
