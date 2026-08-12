from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, replace
from typing import Any, Literal, TypeVar, cast

from openai import APIStatusError, AsyncOpenAI, Omit, RateLimitError, omit
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import (
    ResponseFormatJSONObject,
    ResponseFormatJSONSchema,
)
from pydantic import BaseModel, ValidationError

from flare.config import get_settings
from flare.llm.base import LLMResult
from flare.llm.errors import (
    ModelNotSupportedError,
    ProviderAuthError,
    RateLimitedError,
    StructuredOutputError,
)
from flare.llm.parsing import extract_json
from flare.llm.redaction import redact
from flare.llm.usage import estimate_tokens
from flare.secrets import llm_api_key

T = TypeVar("T", bound=BaseModel)
_logger = logging.getLogger("flare.llm")

Transport = Literal["chat", "responses"]
SchemaMode = Literal["json_schema", "json_object", "prompt_only"]

ResponseFormat = ResponseFormatJSONSchema | ResponseFormatJSONObject


@dataclass(frozen=True)
class _Capabilities:
    transport: Transport = "chat"
    temperature: bool = True
    schema_mode: SchemaMode = "json_schema"


_CAPABILITIES: dict[tuple[str, str], _Capabilities] = {}

_SCHEMA_FALLBACK: dict[SchemaMode, SchemaMode | None] = {
    "json_schema": "json_object",
    "json_object": "prompt_only",
    "prompt_only": None,
}


def reset_capabilities() -> None:
    _CAPABILITIES.clear()


def _mentions(text: str, *needles: str) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def _requires_responses_api(message: str) -> bool:
    return "/v1/responses" in message


def _requires_foreign_api(message: str) -> bool:
    return _mentions(
        message, "anthropic/v1/messages", "/v1/messages", "generatecontent"
    )


def _unknown_model(status: int, message: str) -> bool:
    return status in (400, 404) and _mentions(
        message,
        "no endpoints found",
        "model not found",
        "does not exist",
        "unknown model",
        "invalid model",
        "model_not_found",
    )


def _degrade(caps: _Capabilities, message: str) -> _Capabilities | None:
    if caps.transport == "chat" and _requires_responses_api(message):
        return replace(caps, transport="responses")
    if caps.transport == "responses" and _mentions(message, "/v1/responses"):
        return replace(caps, transport="chat")
    if caps.temperature and _mentions(message, "temperature"):
        return replace(caps, temperature=False)
    if _mentions(
        message,
        "response_format",
        "json_schema",
        "text.format",
        "structured output",
        "response format",
    ):
        weaker = _SCHEMA_FALLBACK[caps.schema_mode]
        if weaker is not None:
            return replace(caps, schema_mode=weaker)
    return None


@dataclass(frozen=True)
class _RawCompletion:
    content: str
    model: str
    tokens_in: int | None
    tokens_out: int | None
    request_id: str | None


@dataclass
class _Attempts:
    repairs: int = 0
    downgrades: int = 0
    rate_limits: int = 0


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    header = getattr(response, "headers", {}) or {}
    raw = header.get("retry-after") or header.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


class OpenAICompatibleClient:
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
            max_retries=0,  # retries/fallback are this class's job, not the SDK's
        )
        self._default_model = settings.llm.models.default
        self._max_repair = settings.llm.max_repair_attempts
        self._max_downgrades = provider.max_capability_downgrades
        self._rate_limit = settings.llm.rate_limit

    # --- capability bookkeeping ------------------------------------------------

    def _capabilities(self, model_id: str) -> _Capabilities:
        return _CAPABILITIES.get((self._base_url, model_id), _Capabilities())

    def _learn(self, model_id: str, caps: _Capabilities, exc: APIStatusError) -> bool:
        message = str(exc)
        if exc.status_code in (401, 403):
            raise ProviderAuthError(
                f"{self._base_url} rejected the credential ({exc.status_code}); "
                f"check llm.provider.api_key: {message}"
            ) from exc
        if _requires_foreign_api(message):
            raise ModelNotSupportedError(
                f"{model_id} needs a non-OpenAI protocol this client does not speak "
                f"({message}). Pick a model served on /v1/chat/completions or "
                "/v1/responses."
            ) from exc
        if _unknown_model(exc.status_code, message):
            raise ModelNotSupportedError(
                f"{self._base_url} will not serve model {model_id!r}: {message}. "
                "Check llm.models.* against https://openrouter.ai/models."
            ) from exc
        if exc.status_code not in (400, 404, 422):
            return False

        degraded = _degrade(caps, message)
        if degraded is None:
            return False
        if _CAPABILITIES.get((self._base_url, model_id)) == degraded:
            return False
        _CAPABILITIES[(self._base_url, model_id)] = degraded
        _logger.info(
            "%s/%s rejected a request shape; degrading %s -> %s",
            self._base_url,
            model_id,
            caps,
            degraded,
        )
        return True

    async def _backoff(self, attempts: _Attempts, exc: Exception) -> bool:
        if attempts.rate_limits >= self._rate_limit.max_retries:
            return False
        attempts.rate_limits += 1
        advised = _retry_after_seconds(exc)
        delay = (
            advised
            if advised is not None
            else self._rate_limit.base_delay_s * (2 ** (attempts.rate_limits - 1))
        )
        delay = min(delay, self._rate_limit.max_delay_s)
        delay *= 1 + random.random() * 0.25
        _logger.warning(
            "%s rate limited (attempt %d/%d); waiting %.1fs",
            self._base_url,
            attempts.rate_limits,
            self._rate_limit.max_retries,
            delay,
        )
        await asyncio.sleep(delay)
        return True

    # --- transports -----------------------------------------------------------

    def _chat_response_format(
        self, caps: _Capabilities, schema_name: str, json_schema: dict[str, Any]
    ) -> ResponseFormat | Omit:
        if caps.schema_mode == "json_schema":
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": json_schema,
                    "strict": False,
                },
            }
        if caps.schema_mode == "json_object":
            return {"type": "json_object"}
        return omit

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

    def _request_id(self, headers: Any) -> str | None:
        if not self._request_id_header:
            return None
        value = headers.get(self._request_id_header)
        return str(value) if value else None

    async def _invoke(
        self,
        *,
        caps: _Capabilities,
        model_id: str,
        system: str,
        turns: list[dict[str, str]],
        temperature: float,
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> _RawCompletion:
        if caps.transport == "responses":
            return await self._call_responses(
                model_id=model_id,
                system=system,
                turns=turns,
                caps=caps,
                schema_name=schema_name,
                json_schema=json_schema,
            )
        return await self._call_chat(
            model_id=model_id,
            system=system,
            turns=turns,
            temperature=temperature,
            caps=caps,
            schema_name=schema_name,
            json_schema=json_schema,
        )

    # --- public surface -------------------------------------------------------

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
        system_with_schema = (
            f"{system}\n\n"
            f"Return ONLY a JSON object conforming to this JSON Schema "
            f"(no prose, no markdown fence, no <think> block):\n{json.dumps(json_schema)}"
        )
        turns: list[dict[str, str]] = [{"role": "user", "content": user}]

        last_error: Exception | None = None
        attempts = _Attempts()
        while attempts.repairs <= self._max_repair:
            caps = self._capabilities(model_id)
            try:
                raw = await self._invoke(
                    caps=caps,
                    model_id=model_id,
                    system=system_with_schema,
                    turns=turns,
                    temperature=temperature,
                    schema_name=schema.__name__,
                    json_schema=json_schema,
                )
            except RateLimitError as exc:
                if await self._backoff(attempts, exc):
                    continue
                raise RateLimitedError(str(exc)) from exc
            except APIStatusError as exc:
                if exc.status_code == 429:
                    if await self._backoff(attempts, exc):
                        continue
                    raise RateLimitedError(str(exc)) from exc
                if attempts.downgrades >= self._max_downgrades:
                    raise
                if not self._learn(model_id, caps, exc):
                    raise
                attempts.downgrades += 1
                continue

            payload = extract_json(raw.content)
            try:
                value = schema.model_validate_json(payload)
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                attempts.repairs += 1
                turns.append({"role": "assistant", "content": raw.content})
                turns.append(
                    {
                        "role": "user",
                        "content": (
                            "Your last reply did not match the schema. "
                            f"Error: {exc}. Reply again with ONLY valid JSON — no "
                            "markdown fence, no commentary, no reasoning block."
                        ),
                    }
                )
                continue

            return self._result(value, raw, system_with_schema, turns)

        raise StructuredOutputError(
            f"{schema.__name__} not produced by {model_id} after "
            f"{self._max_repair + 1} attempts: {last_error}"
        )

    def _result(
        self,
        value: T,
        raw: _RawCompletion,
        system: str,
        turns: list[dict[str, str]],
    ) -> LLMResult[T]:
        tokens_in, tokens_out = raw.tokens_in, raw.tokens_out
        estimated = tokens_in is None and tokens_out is None
        if estimated:
            prompt = system + "".join(turn["content"] for turn in turns)
            tokens_in = estimate_tokens(prompt)
            tokens_out = estimate_tokens(raw.content)
        return LLMResult(
            value=value,
            model=raw.model, 
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            provider_request_id=raw.request_id,
            tokens_estimated=estimated,
        )


__all__ = ["OpenAICompatibleClient", "reset_capabilities"]
