from __future__ import annotations

import httpx

from flare.config import Settings, ToolsSettings, get_settings
from flare.tools.interface import ReadOnlyTool
from flare.tools.real.github import GitHubCodeTool, GitHubDeployTool
from flare.tools.real.http import ReadOnlyHttpBackend
from flare.tools.real.loki import LokiLogsTool
from flare.tools.real.missing import MissingBackendTool
from flare.tools.real.prometheus import PrometheusMetricsTool
from flare.tools.real.unleash import UnleashFlagsTool
from flare.tools.specs import (
    CODE_BLAME,
    DEPLOY_DIFF,
    HISTORY_SEARCH,
    TRACES_QUERY,
)


def _backend(
    tools: ToolsSettings,
    base_url: str,
    *,
    label: str,
    headers: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ReadOnlyHttpBackend:
    return ReadOnlyHttpBackend(
        base_url,
        label=label,
        headers=headers,
        timeout_s=tools.http_timeout_s,
        max_bytes=tools.max_response_bytes,
        transport=transport,
    )


def real_tools(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[ReadOnlyTool]:
    """Every real adapter, with a stated gap wherever a backend is missing."""
    tools = (settings or get_settings()).tools

    adapters: list[ReadOnlyTool] = [
        PrometheusMetricsTool(
            _backend(tools, tools.prometheus.base_url, label="prometheus",
                     transport=transport),
            query_set=tools.prometheus.query_set,
            overrides=tools.prometheus.queries,
        ),
        LokiLogsTool(
            _backend(tools, tools.loki.base_url, label="loki", transport=transport),
            service_label=tools.loki.service_label,
        ),
        MissingBackendTool(
            TRACES_QUERY, "no tracing backend is configured for this deployment"
        ),
        MissingBackendTool(
            HISTORY_SEARCH,
            "past-incident search has no backend yet; incident history lives in "
            "flare's own memory",
        ),
    ]

    github = tools.github
    if github.repo and github.token:
        gh_backend = _backend(
            tools,
            github.api_url,
            label="github",
            headers={
                "Authorization": f"Bearer {github.token.get_secret_value()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            transport=transport,
        )
        adapters.append(GitHubDeployTool(gh_backend, repo=github.repo))
        adapters.append(GitHubCodeTool(gh_backend, repo=github.repo))
    else:
        reason = "GITHUB repo + read-only token are not configured"
        adapters.append(MissingBackendTool(DEPLOY_DIFF, reason))
        adapters.append(MissingBackendTool(CODE_BLAME, reason))

    unleash = tools.unleash
    headers = (
        {"Authorization": unleash.token.get_secret_value()} if unleash.token else None
    )
    adapters.append(
        UnleashFlagsTool(
            _backend(
                tools,
                unleash.base_url,
                label="unleash",
                headers=headers,
                transport=transport,
            ),
            project=unleash.project,
        )
    )
    return adapters