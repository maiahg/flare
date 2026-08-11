import type { IncidentUsage } from "@/lib/api";

const NUMBER = new Intl.NumberFormat();

function Bar({ ratio, exhausted, nearCap }: { ratio: number; exhausted: boolean; nearCap: boolean }) {
  const color = exhausted ? "#a50e0e" : nearCap ? "#8a6d00" : "#137333";
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(ratio * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      style={{
        background: "#eee",
        borderRadius: 4,
        height: 8,
        overflow: "hidden",
        margin: "0.4rem 0",
      }}
    >
      <div
        style={{
          width: `${Math.min(100, ratio * 100)}%`,
          background: color,
          height: "100%",
        }}
      />
    </div>
  );
}

export function TokenUsagePanel({ usage }: { usage: IncidentUsage }) {
  const ratio = usage.budget > 0 ? usage.total / usage.budget : 0;
  const byAgent = usage.by_agent ?? [];
  const byRun = usage.by_run ?? [];
  return (
    <section data-testid="token-usage">
      <h2 style={{ fontSize: "1rem" }}>Token usage</h2>
      <p style={{ margin: 0 }}>
        <strong data-testid="token-total">{NUMBER.format(usage.total)}</strong>{" "}
        tokens across {usage.runs} run{usage.runs === 1 ? "" : "s"}
        {usage.budget > 0 ? (
          <>
            {" "}
            of {NUMBER.format(usage.budget)} budgeted
            {usage.exhausted ? (
              <span data-testid="budget-state" style={{ color: "#a50e0e" }}>
                {" "}
                — budget exhausted, further runs are refused
              </span>
            ) : usage.near_cap ? (
              <span data-testid="budget-state" style={{ color: "#8a6d00" }}>
                {" "}
                — near cap
              </span>
            ) : null}
          </>
        ) : (
          <span style={{ opacity: 0.6 }}> — no incident budget configured</span>
        )}
      </p>
      {usage.budget > 0 ? (
        <Bar ratio={ratio} exhausted={usage.exhausted} nearCap={usage.near_cap} />
      ) : null}
      <p style={{ opacity: 0.6, fontSize: "0.8rem", margin: "0 0 1rem" }}>
        {NUMBER.format(usage.tokens_in)} in / {NUMBER.format(usage.tokens_out)} out.
        The Provider reports tokens, not cost.
      </p>

      <h3 style={{ fontSize: "0.9rem" }}>By agent</h3>
      {byAgent.length === 0 ? (
        <p style={{ opacity: 0.6 }}>No agent has recorded usage yet.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: "0 0 1rem" }}>
          {byAgent.map((agent) => (
            <li key={agent.agent_name} style={{ padding: "0.15rem 0" }}>
              <code>{agent.agent_name}</code>{" "}
              <span style={{ opacity: 0.7 }}>
                {NUMBER.format(agent.tokens_in + agent.tokens_out)} tokens ·{" "}
                {agent.calls} call{agent.calls === 1 ? "" : "s"}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3 style={{ fontSize: "0.9rem" }}>By run</h3>
      {byRun.length === 0 ? (
        <p style={{ opacity: 0.6 }}>No runs yet.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {byRun.map((run) => (
            <li key={run.run_id} style={{ padding: "0.15rem 0" }}>
              <code style={{ fontSize: "0.8rem" }}>{run.run_id.slice(0, 8)}</code>{" "}
              <span style={{ opacity: 0.7 }}>
                {run.run_type ?? "run"} · {run.status ?? "pending"} ·{" "}
                {NUMBER.format(run.tokens_in + run.tokens_out)} tokens
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}