from __future__ import annotations

from collections import deque
from typing import TypeVar

from pydantic import BaseModel

from flare.llm.base import LLMResult

T = TypeVar("T", bound=BaseModel)


class FakeLLMClient:
    """A deterministic LLM for tests: returns queued objects in order."""

    def __init__(self, responses: list[BaseModel] | None = None) -> None:
        self._queue: deque[BaseModel] = deque(responses or [])
        self._defaults: dict[type[BaseModel], BaseModel] = {}
        self.calls: list[dict[str, str]] = [] 

    def enqueue(self, obj: BaseModel) -> None:
        self._queue.append(obj)

    def set_default(self, obj: BaseModel) -> None:
        """Answer any call for ``type(obj)`` the queue cannot satisfy."""
        self._defaults[type(obj)] = obj

    async def structured(
        self,
        *,
        schema: type[T],
        system: str,
        user: str,
        model: str | None = None,
        temperature: float = 0.0,
        trace_name: str | None = None,
    ) -> LLMResult[T]:
        self.calls.append({"system": system, "user": user})
        obj: T
        if self._queue and isinstance(self._queue[0], schema):
            obj = self._queue.popleft()  
        elif schema in self._defaults:
            obj = self._defaults[schema]  
        elif not self._queue:
            raise AssertionError("FakeLLMClient ran out of canned responses")
        else:
            raise AssertionError(
                f"queued {type(self._queue[0]).__name__} but agent asked for "
                f"{schema.__name__}"
            )
        return LLMResult(value=obj, model=model or "fake", tokens_in=1, tokens_out=1)