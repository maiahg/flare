from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from flare.config import get_settings
from flare.llm.redaction import redact, redact_value
from flare.models.tracing import ToolCall
from flare.redis import get_redis
from flare.tools.errors import (
    MutatingToolError,
    NotAllowlistedError,
    RateLimitedToolError,
)
from flare.tools.interface import ReadOnlyTool, ToolResult, read_only_violations

_CACHE_PREFIX = "flare:toolcache:"
_RATE_PREFIX = "flare:toolrate:"


@dataclass(frozen=True)
class BrokeredResult:
    """What an agent gets back: the read plus the id of its audit row."""

    result: ToolResult
    tool_call_id: uuid.UUID
    cached: bool


def _hash_args(name: str, args: dict[str, Any]) -> str:
    payload = json.dumps({"name": name, "args": args}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _redact_args(args: dict[str, Any]) -> dict[str, Any]:
    """Redact string values (recursively) before hashing / persisting."""
    redacted, _ = redact_value(args)
    return dict(redacted)


def _redact_result(result: ToolResult) -> tuple[ToolResult, dict[str, int]]:
    """Scrub a tool result, returning it plus a count of what was replaced."""
    data, data_hits = redact_value(result.data)
    limitations, limit_hits = redact_value(result.limitations)
    hits: dict[str, int] = dict(data_hits)
    for key, count in limit_hits.items():
        hits[key] = hits.get(key, 0) + count
    if not hits:
        return result, {}
    return (
        ToolResult(system=result.system, data=data, limitations=limitations),
        hits,
    )


class ToolBroker:
    """The single, audited, read-only gateway to external systems."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        run_id: uuid.UUID,
        incident_id: uuid.UUID,
        agent_trace_id: uuid.UUID | None = None,
        redis: Redis | None = None,
    ) -> None:
        self._session = session
        self._run_id = run_id
        self._incident_id = incident_id
        self._agent_trace_id = agent_trace_id
        self._redis = redis if redis is not None else get_redis()
        self._registry: dict[str, ReadOnlyTool] = {}
        settings = get_settings().tool_broker
        self._cache_ttl = settings.cache_ttl_s
        self._rate_limit = settings.rate_limit_per_min
        self._timeout = settings.call_timeout_s

    # ---- registration -----------------------------------------------------

    def register(self, tool: ReadOnlyTool) -> None:
        """Register a read-only tool under its ``name``.

        Rejects anything that is not a :class:`ReadOnlyTool` — the only way to
        add a mutating capability would be to change the protocol itself.
        """
        if not isinstance(tool, ReadOnlyTool):
            raise TypeError(
                f"{tool!r} is not a ReadOnlyTool (read-only enforced by construction)"
            )
        violations = read_only_violations(tool)
        if violations:
            raise MutatingToolError(
                f"{type(tool).__name__} exposes mutating method(s) "
                f"{', '.join(violations)}; the broker only mounts read-only "
                "adapters"
            )
        self._registry[tool.name] = tool

    def register_all(self, tools: list[ReadOnlyTool]) -> None:
        for tool in tools:
            self.register(tool)

    @property
    def allowlist(self) -> frozenset[str]:
        return frozenset(self._registry)

    def bind_trace(self, agent_trace_id: uuid.UUID) -> ToolBroker:
        """A shallow copy bound to a different agent trace (shares registry)."""
        clone = ToolBroker(
            self._session,
            run_id=self._run_id,
            incident_id=self._incident_id,
            agent_trace_id=agent_trace_id,
            redis=self._redis,
        )
        clone._registry = self._registry
        return clone

    # ---- the choke point --------------------------------------------------

    async def call(self, name: str, **args: Any) -> BrokeredResult:
        """Invoke a read-only tool: allowlist → cache → rate-limit → audit."""
        tool = self._registry.get(name)
        if tool is None:
            raise NotAllowlistedError(
                f"{name!r} is not an allowlisted tool "
                f"(known: {', '.join(sorted(self._registry)) or 'none'})"
            )

        redacted = _redact_args(args)
        args_hash = _hash_args(name, redacted)

        cached = await self._cache_get(args_hash)
        if cached is not None:
            call_id = await self._audit(
                tool, redacted, args_hash, cached, status="cache_hit", latency_ms=0
            )
            return BrokeredResult(result=cached, tool_call_id=call_id, cached=True)
            # (cached results were redacted before they were cached)

        await self._enforce_rate_limit(name)

        started = time.monotonic()
        status = "ok"
        error: str | None = None
        try:
            result = await tool.read(**args)
        except Exception as exc:  # noqa: BLE001 - degrade, don't crash the graph
            status = "error"
            error = redact(str(exc))
            result = ToolResult(
                system=tool.system,
                data={},
                limitations=[f"{name} unavailable: {exc}"],
            )
        latency_ms = int((time.monotonic() - started) * 1000)

        result, redactions = _redact_result(result)

        if status == "ok":
            await self._cache_set(args_hash, result)

        call_id = await self._audit(
            tool,
            redacted,
            args_hash,
            result,
            status=status,
            latency_ms=latency_ms,
            error=error,
            redactions=redactions,
        )
        return BrokeredResult(result=result, tool_call_id=call_id, cached=False)

    # ---- internals --------------------------------------------------------

    async def _cache_get(self, args_hash: str) -> ToolResult | None:
        raw = await self._redis.get(f"{_CACHE_PREFIX}{args_hash}")
        if raw is None:
            return None
        return ToolResult.model_validate_json(raw)

    async def _cache_set(self, args_hash: str, result: ToolResult) -> None:
        await self._redis.set(
            f"{_CACHE_PREFIX}{args_hash}",
            result.model_dump_json(),
            ex=self._cache_ttl,
        )

    async def _enforce_rate_limit(self, name: str) -> None:
        window = int(time.time() // 60)
        key = f"{_RATE_PREFIX}{self._incident_id}:{name}:{window}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, 60)
        if count > self._rate_limit:
            raise RateLimitedToolError(
                f"{name} exceeded {self._rate_limit} calls/min for incident "
                f"{self._incident_id}"
            )

    async def _audit(
        self,
        tool: ReadOnlyTool,
        redacted_args: dict[str, Any],
        args_hash: str,
        result: ToolResult,
        *,
        status: str,
        latency_ms: int,
        error: str | None = None,
        redactions: dict[str, int] | None = None,
    ) -> uuid.UUID:
        now = datetime.now(UTC)
        call = ToolCall(
            run_id=self._run_id,
            agent_trace_id=self._agent_trace_id,
            tool_name=tool.name,
            system=tool.system,
            args=redacted_args,
            args_hash=args_hash,
            read_only=True,
            status=status,
            latency_ms=latency_ms,
            result_ref={"inline": result.data, "limitations": result.limitations},
            redactions=redactions or None,
            started_at=now,
            finished_at=now,
            error=error,
        )
        self._session.add(call)
        await self._session.flush()
        return call.id