from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import SecretStr

from flare.config import Settings, get_settings

SLACK_SIGNING_SECRET = "slack.signing_secret"
SLACK_CLIENT_SECRET = "slack.client_secret"
SLACK_BOT_TOKEN = "slack.bot_token"
LLM_PROVIDER_API_KEY = "llm.provider.api_key"

class SecretNotFoundError(KeyError):
    """Raised when a requested secret name is unknown to the provider."""

@runtime_checkable
class SecretProvider(Protocol):
    """Anything that can resolve a logical secret name to its value."""
    
    def get_secret(self, name: str) -> str: ...
    
class SettingsSecretProvider:
    """A secret provider that resolves secrets from the application settings."""
    
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
    
    def get_secret(self, name: str) -> str:
        obj: object = self.settings
        for part in name.split("."):
            try:
                obj = getattr(obj, part)
            except AttributeError as e:
                raise SecretNotFoundError(f"Secret '{name}' not found in settings") from e
        if obj is None:
            raise SecretNotFoundError(f"Secret '{name}' is None in settings")
        if isinstance(obj, SecretStr):
            return obj.get_secret_value()
        if isinstance(obj, str):
            return obj
        return str(obj)

_provider: SecretProvider | None = None

def set_secret_provider(provider: SecretProvider | None) -> None:
    """Set the global secret provider."""
    global _provider
    _provider = provider

def get_secret_provider() -> SecretProvider:
    """Get the global secret provider, defaulting to SettingsSecretProvider."""
    global _provider
    if _provider is None:
        _provider = SettingsSecretProvider()
    return _provider

def get_secret(name: str) -> str:
    """Get a secret value by name from the global secret provider."""
    provider = get_secret_provider()
    return provider.get_secret(name)

def get_slack_signing_secret() -> str:
    """Get the Slack signing secret."""
    return get_secret(SLACK_SIGNING_SECRET)

def get_slack_client_secret() -> str:
    """Get the Slack client secret."""
    return get_secret(SLACK_CLIENT_SECRET)

def get_slack_bot_token() -> str:
    """Get the Slack bot token."""
    return get_secret(SLACK_BOT_TOKEN)

def get_openrouter_api_key() -> str:
    """Get the OpenRouter API key."""
    return get_secret(OPENROUTER_API_KEY)