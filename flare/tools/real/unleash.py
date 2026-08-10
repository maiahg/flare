from __future__ import annotations

from typing import Any

from flare.tools.interface import BackendUnavailable, BaseReadOnlyTool, ToolResult
from flare.tools.real.http import ReadOnlyHttpBackend
from flare.tools.specs import FLAGS_AUDIT, FlagsArgs

_NO_HISTORY = (
    "unleash client API exposes current flag state only; flag change history "
    "(who flipped what, when) needs the admin events API"
)


def _rollout_of(strategies: list[dict[str, Any]]) -> int | None:
    for strategy in strategies:
        params = strategy.get("parameters") or {}
        if "rollout" in params:
            try:
                return int(params["rollout"])
            except (TypeError, ValueError):
                return None
    return None


class UnleashFlagsTool(BaseReadOnlyTool):
    spec = FLAGS_AUDIT

    def __init__(self, backend: ReadOnlyHttpBackend, *, project: str = "default") -> None:
        self._backend = backend
        self._project = project

    async def _features(self) -> tuple[list[dict[str, Any]], list[str]]:
        try:
            payload = await self._backend.get_json("/api/client/features")
            return payload.get("features", []), [_NO_HISTORY]
        except BackendUnavailable as client_error:
            try:
                payload = await self._backend.get_json(
                    f"/api/admin/projects/{self._project}/features"
                )
            except BackendUnavailable:
                raise client_error from None
            return payload.get("features", []), []

    async def fetch(self, args: FlagsArgs) -> ToolResult:
        features, limitations = await self._features()
        flags = [
            {
                "key": feature.get("name"),
                "enabled": feature.get("enabled"),
                "type": feature.get("type"),
                "project": feature.get("project", self._project),
                "rollout": _rollout_of(feature.get("strategies") or []),
                "strategies": [
                    s.get("name") for s in (feature.get("strategies") or [])
                ],
                "stale": feature.get("stale"),
                "last_seen_at": feature.get("lastSeenAt"),
            }
            for feature in features
        ]
        if args.key is not None:
            flags = [f for f in flags if f["key"] == args.key]
            if not flags:
                limitations.append(f"no flag named {args.key!r} in this project")

        return ToolResult(
            system=self.system,
            data={"project": self._project, "flags": flags},
            limitations=limitations,
        )