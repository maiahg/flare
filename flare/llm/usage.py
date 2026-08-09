from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flare.llm.base import LLMResult


@dataclass
class LLMUsage:
    """Running total of one agent's LLM spend."""

    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str | None = None
    provider_request_id: str | None = None

    def add(self, result: LLMResult[Any]) -> None:
        """Fold one structured-call result into the running total."""
        self.calls += 1
        self.tokens_in += result.tokens_in or 0
        self.tokens_out += result.tokens_out or 0
        if result.model:
            self.model = result.model
        if result.provider_request_id:
            self.provider_request_id = result.provider_request_id

    def as_dict(self) -> dict[str, int]:
        """Shape persisted to ``agent_traces.tokens`` (JSONB)."""
        return {"in": self.tokens_in, "out": self.tokens_out, "calls": self.calls}