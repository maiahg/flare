import type { IncidentUsage } from "@/lib/api";
import { StatusPill, toneSolid, type Tone } from "@/components/ui/StatusPill";
import { NUMBER } from "@/lib/format";

function Bar({
  ratio,
  exhausted,
  nearCap,
}: {
  ratio: number;
  exhausted: boolean;
  nearCap: boolean;
}) {
  const tone: Tone = exhausted ? "critical" : nearCap ? "warning" : "positive";
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(ratio * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      className="my-2 h-2 overflow-hidden rounded-full bg-[var(--tone-neutral-bg)]"
    >
      <div
        className="h-full rounded-full transition-[width]"
        style={{
          width: `${Math.min(100, ratio * 100)}%`,
          background: toneSolid(tone),
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
      <p className="m-0 text-sm">
        <strong
          data-testid="token-total"
          className="text-2xl font-semibold tabular-nums"
        >
          {NUMBER.format(usage.total)}
        </strong>{" "}
        tokens across {usage.runs} run{usage.runs === 1 ? "" : "s"}
        {usage.budget > 0 ? (
          <>
            {" "}
            of {NUMBER.format(usage.budget)} budgeted
            {usage.exhausted ? (
              <span data-testid="budget-state" className="font-medium text-[var(--tone-critical-fg)]">
                {" "}
                — budget exhausted, further runs are refused
              </span>
            ) : usage.near_cap ? (
              <span data-testid="budget-state" className="font-medium text-[var(--tone-warning-fg)]">
                {" "}
                — near cap
              </span>
            ) : null}
          </>
        ) : (
          <span className="text-[var(--muted)]">
            {" "}
            — no incident budget configured
          </span>
        )}
      </p>
      {usage.budget > 0 ? (
        <Bar ratio={ratio} exhausted={usage.exhausted} nearCap={usage.near_cap} />
      ) : null}
      <p className="mb-5 text-xs text-[var(--muted)]">
        {NUMBER.format(usage.tokens_in)} in / {NUMBER.format(usage.tokens_out)}{" "}
        out. The provider reports tokens, not cost.
      </p>

      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <h3 className="eyebrow mb-2">By agent</h3>
          {byAgent.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">
              No agent has recorded usage yet.
            </p>
          ) : (
            <ul className="m-0 list-none p-0">
              {byAgent.map((agent) => (
                <li
                  key={agent.agent_name}
                  className="flex items-center justify-between gap-3 border-b border-[var(--border)] py-1.5 text-sm last:border-b-0"
                >
                  <span className="truncate">{agent.agent_name}</span>
                  <span className="whitespace-nowrap text-xs tabular-nums text-[var(--muted)]">
                    {NUMBER.format(agent.tokens_in + agent.tokens_out)} tokens ·{" "}
                    {agent.calls} call{agent.calls === 1 ? "" : "s"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h3 className="eyebrow mb-2">By run</h3>
          {byRun.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">No runs yet.</p>
          ) : (
            <ul className="m-0 list-none p-0">
              {byRun.map((run) => (
                <li
                  key={run.run_id}
                  className="flex items-center justify-between gap-3 border-b border-[var(--border)] py-1.5 text-sm last:border-b-0"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <code className="text-xs text-[var(--muted)]">
                      {run.run_id.slice(0, 8)}
                    </code>
                    <span className="truncate">{run.run_type ?? "run"}</span>
                    <StatusPill status={run.status} />
                  </span>
                  <span className="whitespace-nowrap text-xs tabular-nums text-[var(--muted)]">
                    {NUMBER.format(run.tokens_in + run.tokens_out)} tokens
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
