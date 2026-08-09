from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from openai import AsyncOpenAI, APIStatusError, RateLimitError
from pydantic import BaseModel, ValidationError

from flare.config import get_settings
from flare.llm.base import LLMResult
from flare.llm.errors import RateLimitedError, StructuredOutputError, ProviderAuthError
from flare.llm.redaction import redact
from flare.secrets import llm_api_key

T = TypeVar("T", bound=BaseModel)
_logger = logging.getLogger("flare.llm")


class OpenAICompatibleClient:
    """Structured-output client over OpenRouter's OpenAI-compatible endpoint"""

    def __init__(self) -> None:
        settings = get_settings()
        provider = settings.llm.provider
        self._base_url = str(provider.base_url)
        self._request_id_header = provider.request_id_header
        api_key = llm_api_key()
        if api_key is None:
            raise ProviderAuthError(
                "llm.provider.api_key resolved to nothing; the LLM client "
                "cannot be constructed without a credential"
            )
        self._client = AsyncOpenAI(
            base_url=self._base_url,
            api_key=api_key,
            timeout=provider.timeout_seconds,
            default_headers=dict(provider.headers) or None,
            max_retries=0, 
        )
        self._default_model = settings.llm.models.default
        self._max_repair = settings.llm.max_repair_attempts

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
        model_id = model or self._default_model
        user = redact(user)
        json_schema = {
            "name": schema.__name__,
            "schema": schema.model_json_schema(),
            "strict": True,
        }
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        last_error: Exception | None = None
        for attempt in range(self._max_repair + 1):
            try:
                raw = await self._client.chat.completions.with_raw_response.create(
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_schema", "json_schema": json_schema},
                    extra_headers={"Cache-Control": "no-store"},
                )
            except RateLimitError as exc:
                raise RateLimitedError(str(exc)) from exc
            except APIStatusError as exc:
                if exc.status_code == 429:
                    raise RateLimitedError(str(exc)) from exc
                raise

            request_id = (
                raw.headers.get(self._request_id_header)
                if self._request_id_header
                else None
            )
            completion = raw.parse()
            content = completion.choices[0].message.content or ""

            try:
                value = schema.model_validate_json(content)
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your last reply did not match the schema. "
                            f"Error: {exc}. Reply again with ONLY valid JSON."
                        ),
                    }
                )
                continue

            usage = completion.usage
            return LLMResult(
                value=value,
                model=completion.model, 
                tokens_in=getattr(usage, "prompt_tokens", None),
                tokens_out=getattr(usage, "completion_tokens", None),
                provider_request_id=request_id,
            )

        raise StructuredOutputError(
            f"{schema.__name__} not produced after {self._max_repair + 1} attempts: "
            f"{last_error}"
        )