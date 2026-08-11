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
    """Default provider: resolve secrets from the typed :class:`Settings`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()

    def get_secret(self, name: str) -> str:
        obj: object = self._settings
        for part in name.split("."):
            try:
                obj = getattr(obj, part)
            except AttributeError as exc:
                raise SecretNotFoundError(name) from exc
        if obj is None:
            raise SecretNotFoundError(name)
        if isinstance(obj, SecretStr):
            return obj.get_secret_value()
        if isinstance(obj, str):
            return obj
        return str(obj)


_provider: SecretProvider | None = None


def set_secret_provider(provider: SecretProvider | None) -> None:
    """Install the active secret provider (``None`` restores the default)."""
    global _provider
    _provider = provider


def get_secret_provider() -> SecretProvider:
    """Return the active provider, lazily creating the settings-backed default."""
    global _provider
    if _provider is None:
        _provider = SettingsSecretProvider()
    return _provider


def get_secret(name: str) -> str:
    """Resolve a logical secret name to its value via the active provider."""
    return get_secret_provider().get_secret(name)


# --- Named accessors for the known secrets (typed, discoverable call sites) ---


def slack_signing_secret() -> str:
    return get_secret(SLACK_SIGNING_SECRET)


def slack_client_secret() -> str:
    return get_secret(SLACK_CLIENT_SECRET)


def slack_bot_token() -> str:
    return get_secret(SLACK_BOT_TOKEN)


def llm_api_key() -> str | None:
    try:
        return get_secret(LLM_PROVIDER_API_KEY) or None
    except SecretNotFoundError:
        return None
