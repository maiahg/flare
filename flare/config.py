from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, HttpUrl, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PROVIDER_TIMEOUT_SECONDS = 45
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_REQUEST_ID_HEADER = "X-Request-Id"

DEFAULT_FAST_MODEL = "openai/gpt-oss-20b:free"

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

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", env_nested_delimiter="__", case_sensitive=False, extra="ignore")

    database_url: PostgresDsn
    redis_url: RedisDsn
    app_base_url: HttpUrl

    slack: SlackSettings
    llm: LLMSettings = LLMSettings()

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

class LLMModelSettings(BaseModel):
    scribe: str = DEFAULT_FAST_MODEL
    trigger: str = DEFAULT_FAST_MODEL
    default: str = DEFAULT_FAST_MODEL

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