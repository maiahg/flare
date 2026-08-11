from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flare.llm.base import LLMResult

CHARS_PER_TOKEN = 4

def estimate_tokens(text: str) -> int:
    """Rough token count for text a provider declined to meter."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass
class LLMUsage:
    """Running total of one agent's LLM spend."""

    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str | None = None
    provider_request_id: str | None = None
    estimated: bool = False

    def add(self, result: LLMResult[Any]) -> None:
        """Fold one structured-call result into the running total."""
        self.calls += 1
        self.tokens_in += result.tokens_in or 0
        self.tokens_out += result.tokens_out or 0
        if result.tokens_estimated:
            self.estimated = True
        if result.model:
            self.model = result.model
        if result.provider_request_id:
            self.provider_request_id = result.provider_request_id

    def as_dict(self) -> dict[str, int]:
        tokens: dict[str, int] = {
            "in": self.tokens_in,
            "out": self.tokens_out,
            "calls": self.calls,
        }
        if self.estimated:
            tokens["estimated"] = True
        return tokens
