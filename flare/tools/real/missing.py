from __future__ import annotations

from typing import Any

from flare.tools.interface import BaseReadOnlyTool, ToolResult, ToolSpec


class MissingBackendTool(BaseReadOnlyTool):
    """Always degrades, always explains why."""

    def __init__(self, spec: ToolSpec, reason: str) -> None:
        self._spec = spec
        self._reason = reason

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    async def fetch(self, args: Any) -> ToolResult:
        return self.degraded_result(f"{self._spec.name} unavailable: {self._reason}")