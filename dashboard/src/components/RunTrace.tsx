import type { AgentTrace, Run, RunDetail, ToolCall } from "@/lib/api";

function StatusPill({ status }: { status?: string | null }) {
  const color =
    status === "done" || status === "ok"
      ? "#137333"
      : status === "error" || status === "failed"
        ? "#a50e0e"
        : "#8a6d00";
  return (
    <span
      data-testid="status-pill"
      style={{
        fontSize: "0.75rem",
        color,
        border: `1px solid ${color}`,
        borderRadius: 4,
        padding: "0 0.35rem",
      }}
    >
      {status ?? "pending"}
    </span>
  );
}

/**
 * `agent_traces.tokens` is free-form JSONB; the recorder writes
 * `{in, out, calls}` (see flare/llm/usage.py). Read it defensively.
 */
function tokenSummary(tokens: AgentTrace["tokens"]): string | null {
  if (!tokens) return null;
  const asNum = (v: unknown) => (typeof v === "number" ? v : 0);
  const tin = asNum(tokens["in"]);
  const tout = asNum(tokens["out"]);
  const calls = asNum(tokens["calls"]);
  if (tin === 0 && tout === 0 && calls === 0) return null;
  return `${tin} in / ${tout} out · ${calls} call${calls === 1 ? "" : "s"}`;
}

function ToolCallRow({ call }: { call: ToolCall }) {
  return (
    <li style={{ listStyle: "none", padding: "0.25rem 0", opacity: 0.9 }}>
      <code style={{ fontSize: "0.8rem" }}>{call.tool_name}</code>
      {call.system ? (
        <span style={{ opacity: 0.6 }}> · {call.system}</span>
      ) : null}
      {typeof call.latency_ms === "number" ? (
        <span style={{ opacity: 0.6 }}> · {call.latency_ms}ms</span>
      ) : null}{" "}
      <StatusPill status={call.status} />
      {call.error ? (
        <span style={{ color: "#a50e0e" }}> · {call.error}</span>
      ) : null}
    </li>
  );
}

function AgentTraceRow({ trace }: { trace: AgentTrace }) {
  const tokens = tokenSummary(trace.tokens);
  return (
    <li
      data-testid="agent-trace"
      style={{
        listStyle: "none",
        borderLeft: "2px solid #ddd",
        paddingLeft: "0.75rem",
        marginBottom: "0.75rem",
      }}
    >
      <div style={{ fontWeight: 600 }}>
        {trace.seq != null ? `${trace.seq}. ` : ""}
        {trace.agent_name} <StatusPill status={trace.status} />
      </div>
      {trace.model_name || tokens ? (
        <div
          data-testid="trace-usage"
          style={{ fontSize: "0.75rem", opacity: 0.6 }}
        >
          {trace.model_name ?? "—"}
          {tokens ? ` · ${tokens}` : ""}
        </div>
      ) : null}
      {trace.reasoning_summary ? (
        <p style={{ margin: "0.25rem 0", opacity: 0.75, fontSize: "0.85rem" }}>
          {trace.reasoning_summary}
        </p>
      ) : null}
      {trace.tool_calls && trace.tool_calls.length > 0 ? (
        <ul style={{ margin: "0.25rem 0", padding: 0 }}>
          {trace.tool_calls.map((c) => (
            <ToolCallRow key={c.id} call={c} />
          ))}
        </ul>
      ) : (
        <p style={{ margin: 0, opacity: 0.5, fontSize: "0.8rem" }}>
          No tool calls
        </p>
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
  if (runs.length === 0) return <p>No runs yet.</p>;
  return (
    <ul aria-label="runs" style={{ padding: 0, margin: 0 }}>
      {runs.map((r) => (
        <li key={r.id} style={{ listStyle: "none", marginBottom: "0.5rem" }}>
          <button
            onClick={() => onSelect(r.id)}
            disabled={r.id === selectedId}
            style={{ textAlign: "left", width: "100%", padding: "0.5rem" }}
          >
            <strong>{r.run_type}</strong> <StatusPill status={r.status} />
            <br />
            <span style={{ opacity: 0.6, fontSize: "0.8rem" }}>
              {new Date(r.created_at).toLocaleString()}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function RunDetailView({ run }: { run: RunDetail }) {
  const traces = [...(run.agent_traces ?? [])].sort(
    (a, b) => (a.seq ?? 0) - (b.seq ?? 0),
  );
  return (
    <section aria-label="run detail">
      <header style={{ marginBottom: "1rem" }}>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 600 }}>
          {run.run_type} run <StatusPill status={run.status} />
        </h2>
        {run.summary ? <p style={{ opacity: 0.8 }}>{run.summary}</p> : null}
        {run.token_in != null || run.token_out != null ? (
          <p
            data-testid="run-tokens"
            style={{ fontSize: "0.8rem", opacity: 0.7 }}
          >
            Total tokens: {run.token_in ?? 0} in / {run.token_out ?? 0} out
          </p>
        ) : null}
        {run.limitations && run.limitations.length > 0 ? (
          <p style={{ color: "#8a6d00", fontSize: "0.85rem" }}>
            Limitations: {run.limitations.join("; ")}
          </p>
        ) : null}
      </header>
      <ul style={{ padding: 0, margin: 0 }}>
        {traces.map((t) => (
          <AgentTraceRow key={t.id} trace={t} />
        ))}
      </ul>
    </section>
  );
}