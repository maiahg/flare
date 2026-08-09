from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from flare.config import get_settings

_logger = logging.getLogger("flare.llm.tracing")


@contextmanager
def trace(name: str) -> Iterator[None]:
    """A Langfuse span if enabled+installed, else a no-op."""
    settings = get_settings().llm.langfuse
    if not settings.enabled:
        yield
        return
    try:
        from langfuse import Langfuse  
    except ImportError:
        _logger.warning("langfuse enabled but not installed; skipping trace")
        yield
    yield