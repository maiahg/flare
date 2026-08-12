from __future__ import annotations

import base64
import binascii
import fnmatch
from typing import Any

from flare.tools.interface import BaseReadOnlyTool, ToolResult
from flare.tools.real.http import ReadOnlyHttpBackend
from flare.tools.specs import CODE_BLAME, DEPLOY_DIFF, CodeArgs, DeployArgs
from flare.tools.interface import BackendUnavailable

#: Where GitHub looks for CODEOWNERS, in its own precedence order.
_CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


def _commit_summary(commit: dict[str, Any]) -> dict[str, Any]:
    detail = commit.get("commit", {})
    message = (detail.get("message") or "").strip()
    author = commit.get("author") or {}
    return {
        "id": (commit.get("sha") or "")[:7],
        "sha": commit.get("sha"),
        "at": (detail.get("author") or {}).get("date"),
        "author": author.get("login") or (detail.get("author") or {}).get("name"),
        "diff_summary": message.splitlines()[0] if message else "",
        "url": commit.get("html_url"),
    }


class GitHubDeployTool(BaseReadOnlyTool):
    spec = DEPLOY_DIFF

    def __init__(self, backend: ReadOnlyHttpBackend, *, repo: str) -> None:
        self._backend = backend
        self._repo = repo

    async def fetch(self, args: DeployArgs) -> ToolResult:
        if args.deploy_id:
            commit = await self._backend.get_json(
                f"/repos/{self._repo}/commits/{args.deploy_id}"
            )
            summary = _commit_summary(commit)
            summary["files"] = [
                f.get("filename") for f in commit.get("files", []) if f.get("filename")
            ]
            summary["stats"] = commit.get("stats", {})
            return ToolResult(
                system=self.system,
                data={"repo": self._repo, "deploys": [summary]},
            )

        params: dict[str, Any] = {"per_page": args.limit}
        if args.service:
            params["path"] = args.service
        commits = await self._backend.get_json(
            f"/repos/{self._repo}/commits", params=params
        )
        deploys = [_commit_summary(c) for c in commits]
        return ToolResult(
            system=self.system,
            data={"repo": self._repo, "deploys": deploys},
            limitations=[
                "deploys are approximated by commits on the default branch; "
                "actual release times may differ"
            ],
        )


class GitHubCodeTool(BaseReadOnlyTool):
    spec = CODE_BLAME

    def __init__(self, backend: ReadOnlyHttpBackend, *, repo: str) -> None:
        self._backend = backend
        self._repo = repo

    async def _codeowners(self) -> tuple[list[str], str | None]:
        """Raw CODEOWNERS text, or a limitation explaining its absence."""
        for path in _CODEOWNERS_PATHS:
            try:
                payload = await self._backend.get_json(
                    f"/repos/{self._repo}/contents/{path}"
                )
            except BackendUnavailable:
                continue
            try:
                content = base64.b64decode(payload.get("content", "")).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                return [], f"{path} could not be decoded"
            return content.splitlines(), None
        return [], "no CODEOWNERS file found in this repo"

    @staticmethod
    def _owners_for(lines: list[str], path: str) -> list[str]:
        """Last matching CODEOWNERS rule wins, as GitHub does it."""
        owners: list[str] = []
        for line in lines:
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            pattern, *rule_owners = stripped.split()
            if not rule_owners:
                continue
            candidate = pattern.lstrip("/")
            if (
                fnmatch.fnmatch(path, candidate)
                or fnmatch.fnmatch(path, f"{candidate.rstrip('/')}/*")
                or candidate in ("*", "**")
            ):
                owners = rule_owners
        return owners

    async def fetch(self, args: CodeArgs) -> ToolResult:
        path = args.path or args.service
        if path is None:
            return self.degraded_result(
                "no service or path specified for the code read",
                service=None,
                path=None,
                owners=[],
                commits=[],
            )
        commits = await self._backend.get_json(
            f"/repos/{self._repo}/commits", params={"path": path, "per_page": 5}
        )
        lines, owners_limitation = await self._codeowners()

        limitations = [owners_limitation] if owners_limitation else []
        if not commits:
            limitations.append(f"no commits found touching {path!r} in {self._repo}")

        return ToolResult(
            system=self.system,
            data={
                "service": args.service,
                "path": path,
                "owners": self._owners_for(lines, path),
                "commits": [_commit_summary(c) for c in commits],
            },
            limitations=limitations,
        )