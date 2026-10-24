"""One conversation with Claude, with the answer's shape guaranteed."""

import base64
import json
import logging
import time
from collections.abc import Sequence
from types import TracebackType
from typing import Any, Final, Literal, Self

import anthropic
from anthropic.types import (
    Message,
    MessageParam,
    OutputConfigParam,
    TextBlock,
    TextBlockParam,
    Usage,
)
from pydantic import BaseModel, ValidationError

from llmkit.conversation import DEFAULT_MAX_ROUNDS, ToolStream
from llmkit.errors import ClaudeRefused, StructuredOutputError
from llmkit.models import Image, LLMResult, Pricing, Spend
from llmkit.streaming import TextStream
from llmkit.tools import Tool, ToolRunner
from llmkit.transport import translated

DEFAULT_TIMEOUT_SECONDS: Final = 60.0

DEFAULT_MAX_TOKENS: Final = 8_192

TRUNCATED: Final = "the answer was cut off at the token ceiling"

MAX_ATTEMPTS: Final = 2

LOGGED_KEYS: Final = 10

logger = logging.getLogger(__name__)

SDK_RETRIES: Final = 0

CachePolicy = Literal["off", "system", "instructions"]

EPHEMERAL: Final[Any] = {"type": "ephemeral"}


class ClaudeClient:
    """A configured Claude, ready to be asked for one shape of answer."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        pricing: Pricing | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        caching: CachePolicy = "off",
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._model = model
        self._pricing = pricing or Pricing()
        self._max_tokens = max_tokens
        self._caching = caching
        self._client = client or anthropic.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=SDK_RETRIES
        )
        self._owns_client = client is None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Only closes what it opened. A borrowed client stays open."""
        if self._owns_client:
            self._client.close()

    def structured[T: BaseModel](
        self,
        *,
        prompt: str,
        schema: type[T],
        prompt_name: str = "",
        prompt_version: str = "",
        system: str = "",
        system_tail: str = "",
        images: Sequence[Image] = (),
    ) -> LLMResult[T]:
        """Ask for one answer shaped like ``schema``."""
        output = self._format_for(schema)
        messages: list[MessageParam] = [
            {"role": "user", "content": self._content(prompt=prompt, images=images)}
        ]

        started = time.monotonic()
        input_tokens = output_tokens = 0
        cache_write = cache_read = truncated = 0
        last_error = ""

        for attempt in range(1, MAX_ATTEMPTS + 1):
            answer = self._send(
                messages=messages,
                system=system,
                system_tail=system_tail,
                output=output,
            )
            input_tokens += answer.usage.input_tokens
            output_tokens += answer.usage.output_tokens
            cache_write += _written(answer.usage)
            cache_read += _read(answer.usage)
            said: dict[str, object] = {
                "prompt_name": prompt_name,
                "prompt_version": prompt_version,
                "schema": schema.__name__,
                "attempt": attempt,
            }

            if answer.stop_reason == "refusal":
                logger.warning(
                    "llm_answer_refusal",
                    extra={**said, "output_tokens": answer.usage.output_tokens},
                )
                raise ClaudeRefused(
                    f"the model declined to answer {schema.__name__}",
                    schema=schema.__name__,
                    attempts=attempt,
                    spent=self._spend(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_write=cache_write,
                        cache_read=cache_read,
                    ),
                )

            if answer.stop_reason == "max_tokens":
                last_error = TRUNCATED
                truncated += 1
                logger.warning(
                    "llm_answer_truncated",
                    extra={**said, "max_tokens": self._max_tokens},
                )
                messages = [
                    {
                        "role": "user",
                        "content": self._content(
                            prompt=f"{prompt}\n\n{self._shorten()}", images=images
                        ),
                    }
                ]
                continue

            payload = self._payload(answer)
            try:
                value = schema.model_validate(payload)
            except ValidationError as exc:
                last_error = self._readable(exc)
                logger.warning(
                    "llm_answer_invalid",
                    extra={
                        **said,
                        "problem": last_error,
                        "stop_reason": answer.stop_reason,
                        "blocks": [block.type for block in answer.content],
                        "keys": sorted(payload)[:LOGGED_KEYS],
                        "output_tokens": answer.usage.output_tokens,
                    },
                )
                messages += [
                    {"role": "assistant", "content": json.dumps(payload)},
                    {"role": "user", "content": self._correction(last_error)},
                ]
                continue

            spent = self._spend(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_write=cache_write,
                cache_read=cache_read,
            )
            return LLMResult(
                value=value,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_micros=spent.cost_micros,
                currency=self._pricing.currency,
                latency_ms=int((time.monotonic() - started) * 1000),
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                model=self._model,
                attempts=attempt,
                cache_write_tokens=cache_write,
                cache_read_tokens=cache_read,
                truncated=truncated,
            )

        raise StructuredOutputError(
            f"answer did not fit {schema.__name__} after {MAX_ATTEMPTS} attempts: "
            f"{last_error}",
            schema=schema.__name__,
            attempts=MAX_ATTEMPTS,
            spent=self._spend(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_write=cache_write,
                cache_read=cache_read,
            ),
        )

    def stream(
        self,
        *,
        prompt: str,
        system: str = "",
        system_tail: str = "",
        history: tuple[tuple[str, str], ...] = (),
        prompt_name: str = "",
        prompt_version: str = "",
        max_tokens: int = 0,
    ) -> TextStream:
        """Ask for one answer and read it as it is written."""
        messages: list[MessageParam] = [
            {"role": "assistant" if role == "assistant" else "user", "content": text}
            for role, text in history
        ]
        messages.append({"role": "user", "content": prompt})

        return TextStream(
            client=self._client,
            model=self._model,
            max_tokens=max_tokens or self._max_tokens,
            system=self._system_for(system=system, system_tail=system_tail),
            messages=messages,
            pricing=self._pricing,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
        )

    def converse(
        self,
        *,
        prompt: str,
        tools: Sequence[Tool],
        run_tool: ToolRunner,
        system: str = "",
        system_tail: str = "",
        history: tuple[tuple[str, str], ...] = (),
        prompt_name: str = "",
        prompt_version: str = "",
        max_tokens: int = 0,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
    ) -> ToolStream:
        """Ask for one answer that may look things up before it is written."""
        messages: list[MessageParam] = [
            {"role": "assistant" if role == "assistant" else "user", "content": text}
            for role, text in history
        ]
        messages.append({"role": "user", "content": prompt})

        return ToolStream(
            client=self._client,
            model=self._model,
            max_tokens=max_tokens or self._max_tokens,
            system=self._system_for(system=system, system_tail=system_tail),
            messages=messages,
            tools=tools,
            run_tool=run_tool,
            pricing=self._pricing,
            max_rounds=max_rounds,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
        )

    def _send(
        self,
        *,
        messages: list[MessageParam],
        system: str,
        system_tail: str,
        output: OutputConfigParam,
    ) -> Message:
        """One request, with Anthropic's failures translated to ours."""
        with translated():
            return self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system_for(system=system, system_tail=system_tail),
                messages=messages,
                output_config=output,
            )

    @staticmethod
    def _content(*, prompt: str, images: Sequence[Image]) -> Any:
        """The user turn: the prompt alone, or the pictures and then it."""
        if not images:
            return prompt
        blocks: list[Any] = []
        for image in images:
            if image.label:
                blocks.append({"type": "text", "text": image.label})
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.media_type,
                        "data": base64.b64encode(image.data).decode("ascii"),
                    },
                }
            )
        blocks.append({"type": "text", "text": prompt})
        return blocks

    def _system_for(self, *, system: str, system_tail: str) -> Any:
        """The system prompt, as one string or as two blocks with a marker."""
        if not (system or system_tail):
            return anthropic.omit
        alone = self._caching == "instructions" and system and not system_tail
        if not alone and (self._caching == "off" or not (system and system_tail)):
            return "\n\n".join(part for part in (system, system_tail) if part)

        head: TextBlockParam = {
            "type": "text",
            "text": system,
            "cache_control": EPHEMERAL,
        }
        if alone:
            return [head]
        tail: TextBlockParam = {"type": "text", "text": system_tail}
        return [head, tail]

    def _spend(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_write: int,
        cache_read: int,
    ) -> Spend:
        """What the attempts so far cost, at this client's rates."""
        return Spend(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write,
            cache_read_tokens=cache_read,
            cost_micros=self._pricing.cost_micros(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_write_tokens=cache_write,
                cache_read_tokens=cache_read,
            ),
        )

    def count_tokens(
        self,
        *,
        prompt: str,
        system: str = "",
        system_tail: str = "",
        history: tuple[tuple[str, str], ...] = (),
        schema: type[BaseModel] | None = None,
    ) -> int:
        """How many input tokens this request would cost, without asking it."""
        messages: list[MessageParam] = [
            {"role": "assistant" if role == "assistant" else "user", "content": text}
            for role, text in history
        ]
        messages.append({"role": "user", "content": prompt})

        with translated():
            counted = self._client.messages.count_tokens(
                model=self._model,
                system=self._system_for(system=system, system_tail=system_tail),
                messages=messages,
                output_config=(
                    self._format_for(schema) if schema is not None else anthropic.omit
                ),
            )
        return int(counted.input_tokens)

    @staticmethod
    def _format_for(schema: type[BaseModel]) -> OutputConfigParam:
        """The schema, as the one shape the answer may take."""
        return {
            "format": {
                "type": "json_schema",
                "schema": anthropic.transform_schema(schema),
            }
        }

    @staticmethod
    def _payload(answer: Message) -> dict[str, Any]:
        """The answer's JSON object, or an empty dict."""
        for block in answer.content:
            if isinstance(block, TextBlock):
                try:
                    found = json.loads(block.text)
                except json.JSONDecodeError:
                    return {}
                return found if isinstance(found, dict) else {}
        return {}

    @staticmethod
    def _readable(error: ValidationError) -> str:
        """Pydantic's complaint, short enough to hand back to the model."""
        return "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()[:5]
        )

    @staticmethod
    def _shorten() -> str:
        """What to say to an answer that ran out of room."""
        return (
            "That answer was cut off before it finished. Answer again in the "
            "same JSON shape, and make it shorter: keep every required field, "
            "and write the shortest text that still says what each one needs "
            "to say."
        )

    @staticmethod
    def _correction(problem: str) -> str:
        return (
            "That answer did not fit the required shape. Problems:\n"
            f"{problem}\n\n"
            "Answer again in the same JSON shape, fixing only these fields. "
            "Keep everything else exactly as it was."
        )


def _written(usage: Usage) -> int:
    """Tokens written into the cache by this call, or nought."""
    return int(usage.cache_creation_input_tokens or 0)


def _read(usage: Usage) -> int:
    """Tokens served out of the cache. Charged, and not in ``input_tokens``."""
    return int(usage.cache_read_input_tokens or 0)
