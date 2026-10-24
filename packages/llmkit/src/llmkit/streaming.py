"""Claude's answer as it arrives, and what it cost once it has.

Streaming exists for one reason and it is not decoration: an answer that
takes eight seconds to compose reads as a broken page when it appears all
at once, and as a person thinking when it appears as it is written.

Free text here, deliberately, where :meth:`ClaudeClient.structured` forces
a schema. The two are not alternatives - a schema is how an answer becomes
data the product acts on, and this is how an answer becomes a sentence a
person reads. Nothing downstream of this parses what comes back.

Synchronous, like the rest of the package. An async client would be a
second path through the same error translation, the same price arithmetic
and the same accounting - and two paths that must agree are two paths that
eventually do not. Where this runs, blocking is correct anyway: the call
happens inside a Celery task, never inside a request.
"""

import time
from collections.abc import Iterator
from typing import Any, Final

import anthropic
from anthropic.types import MessageParam

from llmkit.errors import LLMError
from llmkit.models import LLMResult, Pricing
from llmkit.transport import translated

# What a half-read stream can honestly report about itself.
NOT_FINISHED: Final = "the stream has not been read to the end yet"


class TextStream:
    """One streamed answer. Iterate for the text, then read ``result``.

    Two objects would be tidier - a generator and a receipt - but the
    receipt is only knowable once the generator is done, and handing back
    a pair invites the caller to keep the wrong half. Here the object is
    the same one before and after, and asking it the wrong question at the
    wrong time raises rather than answering nought.
    """

    def __init__(
        self,
        *,
        client: anthropic.Anthropic,
        model: str,
        max_tokens: int,
        # A string, or the blocks a cache breakpoint needs - whichever the
        # client assembled. Typed loosely on purpose: which of the two it
        # is, is a decision made one layer up and nothing here reads it.
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
        """The answer in pieces, in the order Claude wrote them.

        The pieces are whatever the SDK hands over and carry no meaning of
        their own: a piece may end mid-word, mid-number or mid-sentence.
        Everything downstream of this is written to expect that.
        """
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
            # Counted here as well as in ``structured``, because a streamed
            # answer is charged the same three ways and this is where the
            # caching actually pays: a conversation re-sends the same
            # instructions on every question.
            cache_write_tokens=written,
            cache_read_tokens=served,
            # Free text cut off reads as an answer that simply stopped, and
            # nothing else in it says so - the caller has to be told.
            truncated=int(final.stop_reason == "max_tokens"),
        )

    @property
    def result(self) -> LLMResult[str]:
        """What the answer cost. Only after the stream has been read out.

        Raising rather than returning zeros: a cost of nought written to
        the ledger is indistinguishable from a call that never happened,
        and the month's total is what the ceiling is compared against.
        """
        if self._result is None:
            raise LLMError(NOT_FINISHED)
        return self._result

    @property
    def is_finished(self) -> bool:
        return self._result is not None
