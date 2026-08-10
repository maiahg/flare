from __future__ import annotations

#: Generic OpenTelemetry/Prometheus-client conventions.
DEFAULT: dict[str, str] = {
    "p99_ms": (
        'histogram_quantile(0.99, sum by (le) '
        '(rate(http_request_duration_seconds_bucket{{job="{service}"}}[{window}]))) '
        "* 1000"
    ),
    "error_rate": (
        'sum(rate(http_requests_total{{job="{service}",code=~"5.."}}[{window}])) '
        '/ clamp_min(sum(rate(http_requests_total{{job="{service}"}}[{window}])), 1)'
    ),
    "throughput_rps": 'sum(rate(http_requests_total{{job="{service}"}}[{window}]))',
}

#: A Prometheus scraping itself.
PROMETHEUS_SELF: dict[str, str] = {
    "p99_ms": (
        "histogram_quantile(0.99, sum by (le) "
        '(rate(prometheus_http_request_duration_seconds_bucket{{job="{service}"}}'
        "[{window}]))) * 1000"
    ),
    "error_rate": (
        'sum(rate(prometheus_http_requests_total{{job="{service}",code=~"5.."}}'
        "[{window}])) / clamp_min(sum(rate(prometheus_http_requests_total"
        '{{job="{service}"}}[{window}])), 1)'
    ),
    "throughput_rps": (
        'sum(rate(prometheus_http_requests_total{{job="{service}"}}[{window}]))'
    ),
}

QUERY_SETS: dict[str, dict[str, str]] = {
    "default": DEFAULT,
    "prometheus_self": PROMETHEUS_SELF,
}


def build_query(
    alias: str, *, service: str, window: str, query_set: str, overrides: dict[str, str]
) -> str | None:
    """Render PromQL for ``alias``, or ``None`` if this estate has no mapping."""
    template = overrides.get(alias) or QUERY_SETS.get(query_set, DEFAULT).get(alias)
    if template is None:
        return None
    return template.format(service=service, window=window)