from __future__ import annotations

from dataclasses import dataclass, field

from flare.adaptive.novelty import NoveltyVerdict, signal_text
from flare.agents.schemas import PlannerOutput
from flare.llm import LLMClient, LLMUsage
from flare.llm.injection import UNTRUSTED_DATA_RULE, as_data

#: Read agents keyed by the graph node name that runs them.
AGENT_NAMES = ("telemetry", "deploy", "code", "impact")

#: signal_type -> the read agents that can say something about it.
_SIGNAL_AGENTS: dict[str, tuple[str, ...]] = {
    "deploy": ("deploy",),
    "pr": ("deploy", "code"),
    "commit": ("code",),
    "config": ("deploy", "code"),
    "flag": ("deploy",),
    "metric": ("telemetry",),
    "log": ("telemetry",),
    "stacktrace": ("telemetry", "code"),
    "error": ("telemetry",),
    "symptom": ("telemetry",),
    "time_window": ("telemetry",),
    "service": ("telemetry", "code"),
    "segment": ("impact",),
    "region": ("impact",),
    "plan": ("impact",),
    "endpoint": ("impact",),
    "mitigation": ("deploy", "telemetry"),
    "contradiction": ("telemetry", "deploy"),
    "correction": ("telemetry", "deploy"),
    "command": AGENT_NAMES,
}

_SYSTEM = f"""You are InvestigationPlanner for an incident copilot.
{UNTRUSTED_DATA_RULE}

Choose the smallest subset of the CANDIDATE AGENTS that can actually address the
novel signals, and write a one-sentence focus. You may only choose from the
candidates listed — never invent an agent. Fewer agents is better: each one
costs tool calls and tokens. Return the schema."""


@dataclass
class InvestigationPlan:
    """The targeted plan an adaptive run executes."""

    agents: list[str]
    focus: str = ""
    checking: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    deploy_id: str | None = None
    suspect_service: str | None = None

    def as_dict(self) -> dict[str, object]:
        """The JSON-serializable shape stored in ``RunState['plan']``."""
        return {
            "agents": self.agents,
            "focus": self.focus,
            "checking": self.checking,
            "signals": self.signals,
            "deploy_id": self.deploy_id,
            "suspect_service": self.suspect_service,
        }


def candidate_agents(verdicts: list[NoveltyVerdict]) -> list[str]:
    """Deterministic agent candidates for the novel signals, in graph order."""
    wanted: set[str] = set()
    for v in verdicts:
        if not v.novel:
            continue
        wanted.update(_SIGNAL_AGENTS.get(v.signal_type, ()))
    return [name for name in AGENT_NAMES if name in wanted]


def _hint(verdicts: list[NoveltyVerdict], signal_type: str) -> str | None:
    for v in verdicts:
        if v.novel and v.signal_type == signal_type:
            return signal_text(v.signal)
    return None


class InvestigationPlannerAgent:
    def __init__(self, llm: LLMClient, *, model: str | None = None) -> None:
        self._llm = llm
        self._model = model
        self.usage = LLMUsage()

    async def run(self, *, verdicts: list[NoveltyVerdict]) -> InvestigationPlan:
        """Plan a targeted run. Falls back to the deterministic set on any doubt."""
        candidates = candidate_agents(verdicts)
        novel = [v for v in verdicts if v.novel]
        signals = [f"{v.signal_type}: {signal_text(v.signal)}" for v in novel]

        plan = InvestigationPlan(
            agents=candidates,
            focus="",
            checking=list(candidates),
            signals=signals,
            deploy_id=_hint(novel, "deploy"),
            suspect_service=_hint(novel, "service"),
        )
        if len(candidates) <= 1:
            return plan

        result = await self._llm.structured(
            schema=PlannerOutput,
            system=_SYSTEM,
            user=as_data(
                "NOVEL SIGNALS:\n"
                + ("\n".join(f"- {s}" for s in signals) or "- none")
                + f"\n\nCANDIDATE AGENTS: {', '.join(candidates)}"
            ),
            model=self._model,
            trace_name="planner.plan",
        )
        self.usage.add(result)

        chosen = [a for a in candidates if a in {x.strip().lower() for x in result.value.agents}]
        if chosen:
            plan.agents = chosen
            plan.checking = list(chosen)
        plan.focus = result.value.focus.strip()
        return plan