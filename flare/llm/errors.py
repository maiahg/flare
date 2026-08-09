from __future__ import annotations


class LLMError(Exception):
    """Base class for LLM access failures."""


class StructuredOutputError(LLMError):
    """The model did not return output matching the requested schema."""


class RateLimitedError(LLMError):
    """The provider returned 429 / near-cap; caller should back off."""


class ModelNotSupportedError(LLMError):
    """The configured model cannot be served over this provider's OpenAI API."""


class ProviderAuthError(LLMError):
    """The provider rejected the credential (401/403)."""