from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from flare.tools.interface import BackendUnavailable, BaseReadOnlyTool, ToolResult
from flare.tools.real.http import ReadOnlyHttpBackend
from flare.tools.specs import LOGS_SEARCH, LogsArgs

_LOOKBACK = timedelta(hours=1)

#: LogQL line filters are literal; these characters would change the parse.
_ESCAPE = str.maketrans({'"': '\\"', "\\": "\\\\", "`": "'"})


def _level_of(line: str) -> str:
    lowered = line.lower()
    for level in ("critical", "error", "warn", "info", "debug"):
        if level in lowered:
            return level
    return "unknown"


class LokiLogsTool(BaseReadOnlyTool):
    spec = LOGS_SEARCH

    def __init__(
        self, backend: ReadOnlyHttpBackend, *, service_label: str = "service"
    ) -> None:
        self._backend = backend
        self._label = service_label

    def _logql(self, args: LogsArgs) -> str:
        selector = (
            f'{{{self._label}="{args.service.translate(_ESCAPE)}"}}'
            if args.service
            else f'{{{self._label}=~".+"}}'
        )
        if args.query:
            return f'{selector} |= "{args.query.translate(_ESCAPE)}"'
        return selector

    async def fetch(self, args: LogsArgs) -> ToolResult:
        end = datetime.now(UTC)
        start = end - _LOOKBACK
        payload = await self._backend.get_json(
            "/loki/api/v1/query_range",
            params={
                "query": self._logql(args),
                "start": int(start.timestamp() * 1e9),
                "end": int(end.timestamp() * 1e9),
                "limit": args.limit,
                "direction": "backward",
            },
        )
        if payload.get("status") != "success":
            raise BackendUnavailable(
                f"loki rejected the query: {payload.get('error', 'unknown')}"
            )

        streams: list[dict[str, Any]] = payload.get("data", {}).get("result", [])
        matches: list[dict[str, Any]] = []
        for stream in streams:
            labels = stream.get("stream", {})
            for ts_ns, line in stream.get("values", []):
                at = datetime.fromtimestamp(int(ts_ns) / 1e9, tz=UTC)
                matches.append(
                    {
                        "at": at.strftime("%H:%M:%S"),
                        "service": labels.get(self._label, "unknown"),
                        "level": labels.get("level") or _level_of(line),
                        "text": line,
                    }
                )
        matches.sort(key=lambda m: m["at"])

        limitations = []
        if len(matches) >= args.limit:
            limitations.append(
                f"hit the {args.limit}-line limit; older matches were not read"
            )

        return ToolResult(
            system=self.system,
            data={
                "query": args.query,
                "window": f"{int(_LOOKBACK.total_seconds() // 60)}m",
                "matches": matches[: args.limit],
            },
            limitations=limitations,
        )