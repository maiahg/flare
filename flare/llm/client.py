from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from openai import AsyncOpenAI, APIStatusError, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel, ValidationError

from flare.config import get_settings
from flare.llm.base import LLMResult
from flare.llm.errors import RateLimitedError, StructuredOutputError, ProviderAuthError
from flare.llm.redaction import redact
from flare.secrets import llm_api_key

T = TypeVar("T", bound=BaseModel)
_logger = logging.getLogger("flare.llm")

_RESPONSES_ONLY_MODELS: set[str] = set()


def _requires_responses_api(exc: APIStatusError) -> bool:
    """True for the provider's "use the Responses API instead" 400."""
    return exc.status_code == 400 and "/v1/responses" in str(exc)


@dataclass(frozen=True)
class _RawCompletion:
    """Transport-agnostic result of one provider call."""

    content: str
    model: str
    tokens_in: int | None
    tokens_out: int | None
    request_id: str | None

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
    
    async def _call_chat(
        self,
        *,
        model_id: str,
        system: str,
        turns: list[dict[str, str]],
        temperature: float,
        caps: _Capabilities,
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> _RawCompletion:
        """Call /v1/chat/completions (the default transport)."""
        messages = cast(
            "list[ChatCompletionMessageParam]",
            [{"role": "system", "content": system}, *turns],
        )
        raw = await self._client.chat.completions.with_raw_response.create(
            model=model_id,
            messages=messages,
            temperature=temperature if caps.temperature else omit,
            response_format=self._chat_response_format(caps, schema_name, json_schema),
        )
        completion = raw.parse()
        usage = completion.usage
        choices = completion.choices
        return _RawCompletion(
            content=(choices[0].message.content or "") if choices else "",
            model=completion.model or model_id,
            tokens_in=getattr(usage, "prompt_tokens", None),
            tokens_out=getattr(usage, "completion_tokens", None),
            request_id=self._request_id(raw.headers),
        )

    async def _call_responses(
        self,
        *,
        model_id: str,
        system: str,
        turns: list[dict[str, str]],
        caps: _Capabilities,
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> _RawCompletion:
        """Call /v1/responses for models the provider restricts to that endpoint."""
        text: Any = omit
        if caps.schema_mode == "json_schema":
            text = {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": json_schema,
                    "strict": False,
                }
            }
        elif caps.schema_mode == "json_object":
            text = {"format": {"type": "json_object"}}

        raw = await self._client.responses.with_raw_response.create(
            model=model_id,
            instructions=system,
            input=cast(Any, turns),
            text=text,
        )
        response = raw.parse()
        usage = response.usage
        return _RawCompletion(
            content=response.output_text or "",
            model=response.model or model_id,
            tokens_in=getattr(usage, "input_tokens", None),
            tokens_out=getattr(usage, "output_tokens", None),
            request_id=self._request_id(raw.headers),
        )

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
        json_schema = schema.model_json_schema()
        response_format: ResponseFormatJSONSchema = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": json_schema,
                "strict": False,
            },
        }
        system_with_schema = (
            f"{system}\n\n"
            f"Return ONLY a JSON object conforming to this JSON Schema "
            f"(no prose, no markdown fence):\n{json.dumps(json_schema)}"
        )
        turns: list[dict[str, str]] = [{"role": "user", "content": user}]

        last_error: Exception | None = None
        for _attempt in range(self._max_repair + 1):
            use_responses = model_id in _RESPONSES_ONLY_MODELS
            try:
                if use_responses:
                    raw = await self._call_responses(
                        model_id=model_id,
                        system=system_with_schema,
                        turns=turns,
                        schema_name=schema.__name__,
                        json_schema=json_schema,
                    )
                else:
                    raw = await self._call_chat(
                        model_id=model_id,
                        system=system_with_schema,
                        turns=turns,
                        temperature=temperature,
                        response_format=response_format,
                    )
            except RateLimitError as exc:
                raise RateLimitedError(str(exc)) from exc
            except APIStatusError as exc:
                if exc.status_code == 429:
                    raise RateLimitedError(str(exc)) from exc
                raise

                if not use_responses and _requires_responses_api(exc):
                    _RESPONSES_ONLY_MODELS.add(model_id)
                    _logger.info(
                        "model %s requires the Responses API; switching transport",
                        model_id,
                    )
                    raw = await self._call_responses(
                        model_id=model_id,
                        system=system_with_schema,
                        turns=turns,
                        schema_name=schema.__name__,
                        json_schema=json_schema,
                    )
                else:
                    raise

            try:
                value = schema.model_validate_json(raw.content)
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                turns.append({"role": "assistant", "content": raw.content})
                turns.append(
                    {
                        "role": "user",
                        "content": (
                            "Your last reply did not match the schema. "
                            f"Error: {exc}. Reply again with ONLY valid JSON."
                        ),
                    }
                )
                continue

            return LLMResult(
                value=value,
                model=raw.model, 
                tokens_in=raw.tokens_in,
                tokens_out=raw.tokens_out,
                provider_request_id=raw.request_id
            )

        raise StructuredOutputError(
            f"{schema.__name__} not produced after {self._max_repair + 1} attempts: "
            f"{last_error}"
        )