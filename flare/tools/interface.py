from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """A typed, JSON-serializable read result plus degradation info."""

    system: str
    data: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


@runtime_checkable
class ReadOnlyTool(Protocol):
    """A single read-only capability, addressable by its allowlist ``name``."""

    name: str
    system: str

    async def read(self, **args: Any) -> ToolResult: ...