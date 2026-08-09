from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:  
    """A validated structured response plus provider metadata to persist."""

    value: T
    model: str                       
    tokens_in: int | None = None
    tokens_out: int | None = None
    provider_request_id: str | None = None
    tokens_estimated: bool = False
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class LLMClient(Protocol):
    """Everything the agents need from an LLM: a validated object back."""

    async def structured(
        self,
        *,
        schema: type[T],
        system: str,
        user: str,
        model: str | None = None,
        temperature: float = 0.0,
        trace_name: str | None = None,
    ) -> LLMResult[T]: ...