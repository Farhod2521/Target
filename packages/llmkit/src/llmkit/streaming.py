"""Claude's answer as it arrives, and what it cost once it has."""

import time
from collections.abc import Iterator
from typing import Any, Final

import anthropic
from anthropic.types import MessageParam

from llmkit.errors import LLMError
from llmkit.models import LLMResult, Pricing
from llmkit.transport import translated

NOT_FINISHED: Final = "the stream has not been read to the end yet"


class TextStream:
    """One streamed answer. Iterate for the text, then read ``result``."""

    def __init__(
        self,
        *,
        client: anthropic.Anthropic,
        model: str,
        max_tokens: int,
        system: Any,
        messages: list[MessageParam],
        pricing: Pricing,
        prompt_name: str = "",
        prompt_version: str = "",
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._system = system
        self._messages = messages
        self._pricing = pricing
        self._prompt_name = prompt_name
        self._prompt_version = prompt_version
        self._result: LLMResult[str] | None = None

    def __iter__(self) -> Iterator[str]:
        """The answer in pieces, in the order Claude wrote them."""
        started = time.monotonic()
        collected: list[str] = []

        with (
            translated(),
            self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system,
                messages=self._messages,
            ) as stream,
        ):
            for piece in stream.text_stream:
                collected.append(piece)
                yield piece
            final = stream.get_final_message()

        written = int(final.usage.cache_creation_input_tokens or 0)
        served = int(final.usage.cache_read_input_tokens or 0)
        self._result = LLMResult(
            value="".join(collected),
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            cost_micros=self._pricing.cost_micros(
                input_tokens=final.usage.input_tokens,
                output_tokens=final.usage.output_tokens,
                cache_write_tokens=written,
                cache_read_tokens=served,
            ),
            currency=self._pricing.currency,
            latency_ms=int((time.monotonic() - started) * 1000),
            prompt_name=self._prompt_name,
            prompt_version=self._prompt_version,
            model=self._model,
            cache_write_tokens=written,
            cache_read_tokens=served,
            truncated=int(final.stop_reason == "max_tokens"),
        )

    @property
    def result(self) -> LLMResult[str]:
        """What the answer cost. Only after the stream has been read out."""
        if self._result is None:
            raise LLMError(NOT_FINISHED)
        return self._result

    @property
    def is_finished(self) -> bool:
        return self._result is not None
