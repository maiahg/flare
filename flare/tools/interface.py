from __future__ import annotations

import inspect
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from flare.tools.errors import ToolArgsError

logger = logging.getLogger(__name__)

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


class ToolArgs(BaseModel):
    """Base for a tool's typed arguments."""

    model_config = ConfigDict(extra="forbid")


class ToolResult(BaseModel):
    """A typed, JSON-serializable read result plus degradation info."""

    system: str
    data: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    fetched_at: datetime | None = None

    @property
    def degraded(self) -> bool:
        """True when the read is incomplete — the agent must caveat it."""
        return bool(self.limitations)


class ToolSpec(BaseModel):
    """The frozen description of one read-only capability."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    system: str
    summary: str
    args_model: type[ToolArgs]


@runtime_checkable
class ReadOnlyTool(Protocol):
    """A single read-only capability, addressable by its allowlist ``name``."""

    @property
    def spec(self) -> ToolSpec: ...

    @property
    def name(self) -> str: ...

    @property
    def system(self) -> str: ...

    async def read(self, **args: Any) -> ToolResult: ...


class BackendUnavailable(Exception):
    """Raised by an adapter's ``fetch`` when the backend could not answer."""


class BaseReadOnlyTool(ABC):
    """Implement :meth:`fetch`; inherit validation and degradation."""

    spec: ClassVar[ToolSpec]

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def system(self) -> str:
        return self.spec.system

    @abstractmethod
    async def fetch(self, args: Any) -> ToolResult:
        """Perform the read. Raise :class:`BackendUnavailable` if you cannot."""

    async def read(self, **kwargs: Any) -> ToolResult:
        """Validate args, fetch, and degrade instead of raising"""
        try:
            args = self.spec.args_model.model_validate(kwargs)
        except ValidationError as exc:
            raise ToolArgsError(f"{self.spec.name}: invalid arguments: {exc}") from exc

        try:
            result = await self.fetch(args)
        except BackendUnavailable as exc:
            return self.degraded_result(str(exc))
        except Exception as exc: 
            logger.warning(
                "tool %s failed unexpectedly: %s", self.spec.name, exc, exc_info=True
            )
            return self.degraded_result(f"{self.spec.system} read failed: {exc}")

        if result.fetched_at is None:
            result = result.model_copy(update={"fetched_at": datetime.now(UTC)})
        return result

    def degraded_result(self, limitation: str, **data: Any) -> ToolResult:
        """An empty-but-honest result: no data, an explicit stated gap."""
        return ToolResult(
            system=self.spec.system,
            data=data,
            limitations=[limitation],
            fetched_at=datetime.now(UTC),
        )


def read_only_violations(tool: object) -> list[str]:
    """Public callables on ``tool`` that look like they change something."""
    violations: list[str] = []
    for name in dir(tool):
        if name.startswith("_") or not callable(getattr(tool, name, None)):
            continue
        head = name.split("_", 1)[0].lower()
        if name.lower() in MUTATING_METHOD_NAMES or head in MUTATING_METHOD_NAMES:
            violations.append(name)
    return sorted(violations)


def conforms_to_read_only(tool: object) -> list[str]:
    """Every way ``tool`` fails the read-only contract (empty list = conforms)."""
    problems: list[str] = []
    if not isinstance(getattr(tool, "name", None), str) or not tool.name:  
        problems.append("missing a string `name` (the allowlist key)")
    if not isinstance(getattr(tool, "system", None), str) or not tool.system: 
        problems.append("missing a string `system`")

    spec = getattr(tool, "spec", None)
    if not isinstance(spec, ToolSpec):
        problems.append("has no ToolSpec")
    else:
        if spec.name != getattr(tool, "name", None):
            problems.append("`name` disagrees with `spec.name`")
        if spec.system != getattr(tool, "system", None):
            problems.append("`system` disagrees with `spec.system`")
        if not spec.summary.strip():
            problems.append("spec has an empty summary")
        if not (
            isinstance(spec.args_model, type) and issubclass(spec.args_model, ToolArgs)
        ):
            problems.append("spec.args_model is not a ToolArgs subclass")
        if "." not in spec.name:
            problems.append("spec.name is not `<system>.<verb>`")

    read = getattr(tool, "read", None)
    if read is None or not callable(read):
        problems.append("has no `read` method")
    elif not inspect.iscoroutinefunction(read):
        problems.append("`read` is not async")

    problems.extend(
        f"exposes mutating method `{name}`" for name in read_only_violations(tool)
    )
    if not isinstance(tool, ReadOnlyTool):
        problems.append("does not satisfy the ReadOnlyTool protocol")
    return problems