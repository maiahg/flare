from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, HttpUrl, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PROVIDER_TIMEOUT_SECONDS = 45
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_REQUEST_ID_HEADER = "X-Request-Id"

DEFAULT_FAST_MODEL = "openai/gpt-oss-20b:free"
DEFAULT_REASONING_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"

class SlackSettings(BaseModel):
    signing_secret: SecretStr
    client_id: str
    client_secret: SecretStr
    bot_token: SecretStr

class LLMProviderSettings(BaseModel):
    api_key: SecretStr
    base_url: HttpUrl = HttpUrl(OPENROUTER_BASE_URL)
    timeout_seconds: int = DEFAULT_PROVIDER_TIMEOUT_SECONDS
    request_id_header: str | None = OPENROUTER_REQUEST_ID_HEADER
    headers: dict[str, str] = {}

class LLMModelSettings(BaseModel):
    scribe: str = DEFAULT_FAST_MODEL
    trigger: str = DEFAULT_FAST_MODEL
    default: str = DEFAULT_FAST_MODEL
    hypothesis: str = DEFAULT_REASONING_MODEL
    critic: str = DEFAULT_REASONING_MODEL
    summarizer: str = DEFAULT_REASONING_MODEL
    planner: str = DEFAULT_FAST_MODEL
    mitigation: str = DEFAULT_REASONING_MODEL

class LangfuseSettings(BaseModel):
    enabled: bool = False
    host: HttpUrl | None = None
    public_key: SecretStr | None = None
    seceret_key: SeceretStr | None = None

class LLMSettings(BaseModel):
    provider: LLMProviderSettings = LLMProviderSettings()
    models: LLMModelSettings = LLMModelSettings()
    langfuse: LangfuseSettings = LangfuseSettings()
    max_repair_attempts: int = 1
    rate_limit: LLMRateLimitSettings = LLMRateLimitSettings()

class RunBudgetSettings(BaseModel):
    """Per-run investigation budget."""

    max_tokens: int = 120_000
    max_tool_calls: int = 40
    max_wall_clock_s: int = 90
    fan_out_concurrency: int = 4
    max_critic_revisions: int = 2


class ToolBrokerSettings(BaseModel):
    """Tool Broker cache + rate-limit tunables."""

    cache_ttl_s: int = 60
    rate_limit_per_min: int = 60
    call_timeout_s: int = 15

class AdaptiveSettings(BaseModel):
    """Trigger scoring + debounce/coalesce tunables"""

    trigger_threshold: float = 0.5
    batch_threshold: float = 0.2
    coalesce_window_s: int = 30
    pending_ttl_s: int = 600
    max_coalesced_signals: int = 50

class MitigationSettings(BaseModel):
    """Mitigation proposals + the approval gate"""

    enabled: bool = True
    max_options: int = 3

class GovernorSettings(BaseModel):
    """Anti-spam governor budget + dedup tunables"""

    post_budget: int = 6
    post_window_s: int = 900
    dedup_ttl_s: int = 1800
    dedup_similarity: float = 0.85
    dedup_history: int = 20

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", env_nested_delimiter="__", case_sensitive=False, extra="ignore")

    database_url: PostgresDsn
    redis_url: RedisDsn
    app_base_url: HttpUrl

    slack: SlackSettings
    llm: LLMSettings = LLMSettings()
    run_budget: RunBudgetSettings = RunBudgetSettings()
    tool_broker: ToolBrokerSettings = ToolBrokerSettings()
    adaptive: AdaptiveSettings = AdaptiveSettings()
    governor: GovernorSettings = GovernorSettings()
    mitigation: MitigationSettings = MitigationSettings()

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()