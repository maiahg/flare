from __future__ import annotations

from flare.llm.base import LLMClient

_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        from flare.llm.client import OpenAICompatibleClient
        _client = OpenAICompatibleClient()
    return _client


def set_llm_client(client: LLMClient | None) -> None:
    """Install a client (e.g. a FakeLLMClient in tests); None restores default."""
    global _client
    _client = client