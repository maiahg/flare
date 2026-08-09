from __future__ import annotations

from typing import Literal

from pydantic import Field

from flare.tools.interface import ToolArgs, ToolSpec

MetricAlias = Literal["p99_ms", "error_rate", "throughput_rps"]


class MetricsArgs(ToolArgs):
    service: str = "checkout-api"
    metric: MetricAlias = "p99_ms"
    window_minutes: int = Field(default=60, ge=1, le=1440)


class LogsArgs(ToolArgs):
    query: str = ""
    service: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class TracesArgs(ToolArgs):
    service: str | None = None
    window_minutes: int = Field(default=5, ge=1, le=1440)


class DeployArgs(ToolArgs):
    deploy_id: str | None = None
    service: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


class CodeArgs(ToolArgs):
    service: str = "payments-svc"
    path: str | None = None


class FlagsArgs(ToolArgs):
    key: str | None = None


class HistoryArgs(ToolArgs):
    query: str = ""
    limit: int = Field(default=20, ge=1, le=100)


METRICS_QUERY = ToolSpec(
    name="metrics.query",
    system="metrics",
    summary="Time series for a service metric over a window.",
    args_model=MetricsArgs,
)

LOGS_SEARCH = ToolSpec(
    name="logs.search",
    system="logs",
    summary="Recent log lines matching a substring, optionally per service.",
    args_model=LogsArgs,
)

TRACES_QUERY = ToolSpec(
    name="traces.query",
    system="traces",
    summary="Sampled distributed-trace spans over a recent window.",
    args_model=TracesArgs,
)

DEPLOY_DIFF = ToolSpec(
    name="deploy.diff",
    system="deploy",
    summary="Recent deploys with their change summary and timing.",
    args_model=DeployArgs,
)

CODE_BLAME = ToolSpec(
    name="code.blame",
    system="code",
    summary="Recent changes and owners for a service's code.",
    args_model=CodeArgs,
)

FLAGS_AUDIT = ToolSpec(
    name="flags.audit",
    system="flags",
    summary="Feature flag states and recent changes.",
    args_model=FlagsArgs,
)

HISTORY_SEARCH = ToolSpec(
    name="history.search",
    system="history",
    summary="Past incidents matching a query.",
    args_model=HistoryArgs,
)

CATALOGUE: tuple[ToolSpec, ...] = (
    METRICS_QUERY,
    LOGS_SEARCH,
    TRACES_QUERY,
    DEPLOY_DIFF,
    CODE_BLAME,
    FLAGS_AUDIT,
    HISTORY_SEARCH,
)

CATALOGUE_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in CATALOGUE}