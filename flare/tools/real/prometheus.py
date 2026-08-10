from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from flare.tools.interface import BaseReadOnlyTool, ToolResult
from flare.tools.real.http import ReadOnlyHttpBackend
from flare.tools.real.promql import build_query
from flare.tools.specs import METRICS_QUERY, MetricsArgs

_TARGET_POINTS = 60


def _rate_window(window_minutes: int) -> str:
    """Rate window that keeps a counter's rate meaningful at this resolution."""
    return f"{max(1, window_minutes // 10)}m"


class PrometheusMetricsTool(BaseReadOnlyTool):
    spec = METRICS_QUERY

    def __init__(
        self,
        backend: ReadOnlyHttpBackend,
        *,
        query_set: str = "default",
        overrides: dict[str, str] | None = None,
    ) -> None:
        self._backend = backend
        self._query_set = query_set
        self._overrides = overrides or {}

    async def fetch(self, args: MetricsArgs) -> ToolResult:
        query = build_query(
            args.metric,
            service=args.service,
            window=_rate_window(args.window_minutes),
            query_set=self._query_set,
            overrides=self._overrides,
        )
        if query is None:
            return self.degraded_result(
                f"no PromQL mapping configured for metric {args.metric!r}",
                service=args.service,
                metric=args.metric,
                series={},
            )

        end = datetime.now(UTC)
        start = end - timedelta(minutes=args.window_minutes)
        step = max(15, int(args.window_minutes * 60 / _TARGET_POINTS))
        payload = await self._backend.get_json(
            "/api/v1/query_range",
            params={
                "query": query,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": f"{step}s",
            },
        )

        if payload.get("status") != "success":
            return self.degraded_result(
                f"prometheus rejected the query: {payload.get('error', 'unknown')}",
                service=args.service,
                metric=args.metric,
                series={},
            )

        results: list[dict[str, Any]] = payload.get("data", {}).get("result", [])
        if not results:
            return self.degraded_result(
                f"prometheus has no {args.metric} series for {args.service!r} "
                f"in the last {args.window_minutes}m",
                service=args.service,
                metric=args.metric,
                series={},
            )

        series: dict[str, float] = {}
        for timestamp, value in results[0].get("values", []):
            label = datetime.fromtimestamp(float(timestamp), tz=UTC).strftime("%H:%M")
            try:
                series[label] = round(float(value), 4)
            except ValueError:
                continue

        limitations = []
        if len(results) > 1:
            limitations.append(
                f"{len(results)} series matched; showing the first "
                f"({results[0].get('metric', {})})"
            )
        if not series:
            limitations.append("all samples in the window were NaN")

        return ToolResult(
            system=self.system,
            data={
                "service": args.service,
                "metric": args.metric,
                "query": query,
                "series": series,
            },
            limitations=limitations,
        )