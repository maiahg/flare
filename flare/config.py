from __future__ import annotations

from functools import lru_cache
from typing import Literal, Mapping

from pydantic import (
    BaseModel,
    HttpUrl,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_LLM_TIMEOUT_SECONDS = 45

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_REQUEST_ID_HEADER = "X-Request-Id"

DEFAULT_FAST_MODEL = "openai/gpt-oss-120b"
DEFAULT_REASONING_MODEL = "openai/gpt-5.6-luna"


INHERIT_TIER = ""

ROLE_TIERS: Mapping[str, str] = {
    "default": "fast",
    "scribe": "fast",
    "trigger": "fast",
    "planner": "fast",
    "hypothesis": "reasoning",
    "critic": "reasoning",
    "summarizer": "reasoning",
    "mitigation": "reasoning",
    "verifier": "reasoning",
    "postmortem": "reasoning",
}


class SlackSettings(BaseModel):
    signing_secret: SecretStr
    client_id: str
    client_secret: SecretStr
    bot_token: SecretStr


class LLMProviderSettings(BaseModel):
    base_url: HttpUrl = HttpUrl(OPENROUTER_BASE_URL)
    api_key: SecretStr | None = None
    timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS
    request_id_header: str | None = OPENROUTER_REQUEST_ID_HEADER
    headers: dict[str, str] = {}
    max_capability_downgrades: int = 4


class LLMModelSettings(BaseModel):
    fast: str = INHERIT_TIER
    reasoning: str = INHERIT_TIER

    default: str = INHERIT_TIER
    scribe: str = INHERIT_TIER
    trigger: str = INHERIT_TIER
    planner: str = INHERIT_TIER
    hypothesis: str = INHERIT_TIER
    critic: str = INHERIT_TIER
    summarizer: str = INHERIT_TIER
    mitigation: str = INHERIT_TIER
    verifier: str = INHERIT_TIER
    postmortem: str = INHERIT_TIER

    def resolved(self) -> LLMModelSettings:
        fast = self.fast or DEFAULT_FAST_MODEL
        reasoning = self.reasoning or self.fast or DEFAULT_REASONING_MODEL
        tiers = {"fast": fast, "reasoning": reasoning}
        roles = {
            role: getattr(self, role) or tiers[tier]
            for role, tier in ROLE_TIERS.items()
        }
        return LLMModelSettings(fast=fast, reasoning=reasoning, **roles)


class LangfuseSettings(BaseModel):
    enabled: bool = False
    host: HttpUrl | None = None
    public_key: SecretStr | None = None
    secret_key: SecretStr | None = None


class LLMRateLimitSettings(BaseModel):
    max_retries: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 20.0


class LLMSettings(BaseModel):
    provider: LLMProviderSettings = LLMProviderSettings()
    models: LLMModelSettings = LLMModelSettings()
    langfuse: LangfuseSettings = LangfuseSettings()
    max_repair_attempts: int = 1
    rate_limit: LLMRateLimitSettings = LLMRateLimitSettings()


class RunBudgetSettings(BaseModel):
    max_tokens: int = 120_000
    max_tool_calls: int = 40
    max_wall_clock_s: int = 90
    fan_out_concurrency: int = 4
    max_critic_revisions: int = 2


class IncidentBudgetSettings(BaseModel):
    max_tokens: int = 2_000_000
    warn_ratio: float = 0.8


class ToolBrokerSettings(BaseModel):
    cache_ttl_s: int = 60
    rate_limit_per_min: int = 60
    call_timeout_s: int = 15


class PrometheusSettings(BaseModel):
    base_url: str = "http://localhost:9090"
    query_set: Literal["default", "prometheus_self"] = "default"
    queries: dict[str, str] = {}


class LokiSettings(BaseModel):
    base_url: str = "http://localhost:3100"
    service_label: str = "service"


class GitHubSettings(BaseModel):
    api_url: str = "https://api.github.com"
    repo: str | None = None
    token: SecretStr | None = None


class UnleashSettings(BaseModel):
    base_url: str = "http://localhost:4242"
    token: SecretStr | None = None
    project: str = "default"


class ToolsSettings(BaseModel):
    provider: Literal["synthetic", "real"] = "synthetic"
    default_service: str | None = None
    http_timeout_s: float = 5.0
    max_response_bytes: int = 2_000_000
    prometheus: PrometheusSettings = PrometheusSettings()
    loki: LokiSettings = LokiSettings()
    github: GitHubSettings = GitHubSettings()
    unleash: UnleashSettings = UnleashSettings()


class AdaptiveSettings(BaseModel):
    trigger_threshold: float = 0.5
    batch_threshold: float = 0.2
    coalesce_window_s: int = 30
    pending_ttl_s: int = 600
    max_coalesced_signals: int = 50


class MitigationSettings(BaseModel):
    enabled: bool = True
    max_options: int = 3


class ActiveModeSettings(BaseModel):
    refresh_interval_s: int = 300
    min_refresh_interval_s: int = 60
    agents: tuple[str, ...] = ("telemetry", "impact")


class RecoverySettings(BaseModel):
    poll_interval_s: int = 60
    max_polls: int = 20
    metric: str = "p99_ms"
    window_minutes: int = 60
    recovered_ratio: float = 1.5
    degraded_ratio: float = 2.0
    default_service: str | None = None
    scenario: str | None = None


class GovernorSettings(BaseModel):
    post_budget: int = 6
    post_window_s: int = 900
    dedup_ttl_s: int = 1800
    dedup_similarity: float = 0.85
    dedup_history: int = 20


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: PostgresDsn
    redis_url: RedisDsn
    app_base_url: HttpUrl
    dashboard_base_url: HttpUrl

    slack: SlackSettings
    llm: LLMSettings = LLMSettings()
    run_budget: RunBudgetSettings = RunBudgetSettings()
    incident_budget: IncidentBudgetSettings = IncidentBudgetSettings()
    tool_broker: ToolBrokerSettings = ToolBrokerSettings()
    tools: ToolsSettings = ToolsSettings()
    adaptive: AdaptiveSettings = AdaptiveSettings()
    governor: GovernorSettings = GovernorSettings()
    mitigation: MitigationSettings = MitigationSettings()
    active: ActiveModeSettings = ActiveModeSettings()
    recovery: RecoverySettings = RecoverySettings()

    @model_validator(mode="after")
    def _resolve_llm(self) -> Settings:
        if self.llm.provider.api_key is None:
            raise ValueError(
                "llm.provider.api_key is required (set LLM__PROVIDER__API_KEY — "
                "get one at https://openrouter.ai/keys)"
            )
        self.llm.models = self.llm.models.resolved()
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
