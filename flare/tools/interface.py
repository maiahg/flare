from __future__ import annotations

import inspect
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

MUTATING_METHOD_NAMES: frozenset[str] = frozenset(
    {
        "write",
        "create",
        "update",
        "patch",
        "put",
        "post",
        "delete",
        "remove",
        "destroy",
        "drop",
        "truncate",
        "purge",
        "apply",
        "mutate",
        "execute",
        "run_command",
        "exec",
        "shell",
        "rollback",
        "revert",
        "deploy",
        "redeploy",
        "restart",
        "reboot",
        "scale",
        "resize",
        "disable",
        "enable",
        "toggle",
        "set",
        "send",
        "page",
        "notify",
        "publish",
        "trigger",
        "kill",
        "terminate",
        "drain",
        "failover",
        "flush",
        "rotate",
        "reset",
    }
)

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