from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from flare.tools.errors import ToolArgsError
from flare.tools.interface import (
    ReadOnlyTool,
    ToolResult,
    conforms_to_read_only,
)

ToolFactory = Callable[[], ReadOnlyTool]


@dataclass(frozen=True)
class AdapterCase:
    """One adapter, plus the ways to build it healthy and broken."""

    label: str
    healthy: ToolFactory
    args: dict[str, Any]
    outage: ToolFactory | None = None
    malformed: ToolFactory | None = None
    bad_args: dict[str, Any] = field(
        default_factory=lambda: {"definitely_not_a_real_argument": 1}
    )


@dataclass
class ContractCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class ContractReport:
    label: str
    checks: list[ContractCheck]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[ContractCheck]:
        return [c for c in self.checks if not c.ok]


def _json_safe(result: ToolResult) -> bool:
    """The result has to survive the audit row, the cache, and the prompt."""
    try:
        json.dumps(result.model_dump(mode="json"))
    except (TypeError, ValueError):
        return False
    return True


async def run_contract(case: AdapterCase) -> ContractReport:
    """Run every contract check against one adapter."""
    checks: list[ContractCheck] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append(ContractCheck(name=name, ok=ok, detail=detail))

    tool = case.healthy()

    # --- shape -------------------------------------------------------------
    problems = conforms_to_read_only(tool)
    record("read-only surface + declared spec", not problems, "; ".join(problems))

    # --- happy path --------------------------------------------------------
    try:
        result = await tool.read(**case.args)
        raised: Exception | None = None
    except Exception as exc: 
        result, raised = None, exc 

    record(
        "healthy read returns without raising",
        raised is None,
        f"{type(raised).__name__}: {raised}" if raised else "",
    )
    if result is not None:
        record("returns a ToolResult", isinstance(result, ToolResult))
        record(
            "result.system matches the spec",
            result.system == tool.spec.system,
            f"{result.system} != {tool.spec.system}",
        )
        record("result is JSON-serializable", _json_safe(result))
        record(
            "result carries an `as of` timestamp",
            result.fetched_at is not None,
        )
        record(
            "healthy read is not degraded",
            not result.degraded,
            str(result.limitations),
        )

    # --- idempotence -------------------------------------------------------
    # A read must be safe to repeat: the broker caches, retries, and replays.
    if result is not None:
        again = await case.healthy().read(**case.args)
        record(
            "repeating the read yields the same data",
            again.data == result.data,
            "second read differed",
        )

    # --- caller errors are loud -------------------------------------------
    try:
        await tool.read(**case.bad_args)
        record("invalid arguments raise ToolArgsError", False, "no error raised")
    except ToolArgsError:
        record("invalid arguments raise ToolArgsError", True)
    except Exception as exc:
        record(
            "invalid arguments raise ToolArgsError",
            False,
            f"raised {type(exc).__name__} instead",
        )

    # --- backend errors are quiet and honest -------------------------------
    for label, factory in (("outage", case.outage), ("malformed", case.malformed)):
        if factory is None:
            continue
        broken = factory()
        try:
            degraded = await broken.read(**case.args)
            raised = None
        except Exception as exc:  
            degraded, raised = None, exc 
        record(
            f"{label} backend does not raise into the graph",
            raised is None,
            f"{type(raised).__name__}: {raised}" if raised else "",
        )
        if degraded is not None:
            record(
                f"{label} backend reports a limitation",
                degraded.degraded,
                "no limitation recorded — the gap would be invisible",
            )
            record(
                f"{label} result is still JSON-serializable",
                _json_safe(degraded),
            )
            findings = {
                key: value
                for key, value in degraded.data.items()
                if isinstance(value, list | dict) and value
            }
            record(
                f"{label} result carries no findings",
                not findings,
                f"returned observations while degraded: {sorted(findings)}",
            )

    return ContractReport(label=case.label, checks=checks)


async def run_contracts(cases: list[AdapterCase]) -> list[ContractReport]:
    return [await run_contract(case) for case in cases]