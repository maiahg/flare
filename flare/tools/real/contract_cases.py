from __future__ import annotations

import httpx

from flare.tools.contract import AdapterCase
from flare.tools.real.fixtures import (
    dead_transport,
    fixture_transport,
    malformed_transport,
)
from flare.tools.real.github import GitHubCodeTool, GitHubDeployTool
from flare.tools.real.http import ReadOnlyHttpBackend
from flare.tools.real.loki import LokiLogsTool
from flare.tools.real.missing import MissingBackendTool
from flare.tools.real.prometheus import PrometheusMetricsTool
from flare.tools.real.unleash import UnleashFlagsTool
from flare.tools.specs import HISTORY_SEARCH, TRACES_QUERY

PROM_ROUTES = {"/api/v1/query_range": "prometheus_query_range"}
LOKI_ROUTES = {"/loki/api/v1/query_range": "loki_query_range"}
UNLEASH_ROUTES = {"/api/client/features": "unleash_client_features"}
GITHUB_ROUTES = {
    "/repos/acme/checkout/contents/": "github_codeowners",
    "/repos/acme/checkout/commits/": "github_commit_detail",
    "/repos/acme/checkout/commits": "github_commits",
}


def backend(
    base_url: str, label: str, transport: httpx.AsyncBaseTransport
) -> ReadOnlyHttpBackend:
    return ReadOnlyHttpBackend(
        base_url, label=label, timeout_s=1.0, transport=transport
    )


def real_cases() -> tuple[list[AdapterCase], set[str]]:
    """Every real adapter as a contract case, plus the names they cover."""

    def prometheus(transport: httpx.AsyncBaseTransport) -> PrometheusMetricsTool:
        return PrometheusMetricsTool(
            backend("http://prometheus:9090", "prometheus", transport),
            query_set="prometheus_self",
        )

    def loki(transport: httpx.AsyncBaseTransport) -> LokiLogsTool:
        return LokiLogsTool(backend("http://loki:3100", "loki", transport))

    def unleash(transport: httpx.AsyncBaseTransport) -> UnleashFlagsTool:
        return UnleashFlagsTool(backend("http://unleash:4242", "unleash", transport))

    def gh_deploy(transport: httpx.AsyncBaseTransport) -> GitHubDeployTool:
        return GitHubDeployTool(
            backend("https://api.github.com", "github", transport), repo="acme/checkout"
        )

    def gh_code(transport: httpx.AsyncBaseTransport) -> GitHubCodeTool:
        return GitHubCodeTool(
            backend("https://api.github.com", "github", transport), repo="acme/checkout"
        )

    cases = [
        AdapterCase(
            label="prometheus metrics.query",
            healthy=lambda: prometheus(fixture_transport(PROM_ROUTES)),
            args={"service": "prometheus", "metric": "p99_ms"},
            outage=lambda: prometheus(dead_transport()),
            malformed=lambda: prometheus(malformed_transport()),
        ),
        AdapterCase(
            label="loki logs.search",
            healthy=lambda: loki(fixture_transport(LOKI_ROUTES)),
            args={"query": "pool", "limit": 100},
            outage=lambda: loki(dead_transport(timeout=True)),
            malformed=lambda: loki(malformed_transport()),
        ),
        AdapterCase(
            label="unleash flags.audit",
            healthy=lambda: unleash(fixture_transport(UNLEASH_ROUTES)),
            args={},
            outage=lambda: unleash(dead_transport()),
            malformed=lambda: unleash(malformed_transport()),
            standing_limitations=True,
        ),
        AdapterCase(
            label="github deploy.diff",
            healthy=lambda: gh_deploy(fixture_transport(GITHUB_ROUTES)),
            args={"limit": 3},
            outage=lambda: gh_deploy(dead_transport()),
            malformed=lambda: gh_deploy(malformed_transport()),
            standing_limitations=True,
        ),
        AdapterCase(
            label="github code.blame",
            healthy=lambda: gh_code(fixture_transport(GITHUB_ROUTES)),
            args={"service": "checkout-api", "path": "docs/README.md"},
            outage=lambda: gh_code(dead_transport()),
            malformed=lambda: gh_code(malformed_transport()),
        ),
        AdapterCase(
            label="missing traces.query",
            healthy=lambda: MissingBackendTool(TRACES_QUERY, "no tracing backend"),
            args={"window_minutes": 5},
            always_degraded=True,
        ),
        AdapterCase(
            label="missing history.search",
            healthy=lambda: MissingBackendTool(HISTORY_SEARCH, "no history backend"),
            args={"query": "latency"},
            always_degraded=True,
        ),
    ]
    names = {case.healthy().name for case in cases}
    return cases, names

