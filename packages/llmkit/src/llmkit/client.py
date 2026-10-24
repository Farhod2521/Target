"""One conversation with Claude, with the answer's shape guaranteed.

Free text is never parsed. Every call names a pydantic schema, and the
schema is sent as the format the answer must take (``output_config``) -
which turns "please answer in JSON" from a request into a constraint the
API holds while the answer is being written. What comes back is an
instance of the schema or an error, never a string somebody has to guess
at.

**Not a tool.** The schema is not sent as a tool Claude is forced to call,
and two things rule that out. The arguments of a forced call are never
checked against the schema, so an answer with none of the fields arrives
as an empty call and is reported as every field missing. And some of the
newest models refuse a forced ``tool_choice`` outright, with a four
hundred.

**Held there, and checked here.** The shape - which keys, which types,
which values of an enum, and no keys beyond those - is enforced on
Anthropic's side. Lengths, numeric bounds and list sizes are not: the API
refuses a schema that carries them, so they leave the schema that is sent
(for the field's description, where the model still reads them) and
pydantic checks them once the answer is in. That split is why the re-ask
below exists.

The package holds no configuration: the key, the model, the prices and the
timeout all arrive through the constructor, and the current time arrives as
a measurement rather than a lookup. That is what lets this move to another
project unchanged.
"""

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

# Long enough for a considered answer, short enough that a stuck request
# does not hold a Celery worker for the whole task time limit.
DEFAULT_TIMEOUT_SECONDS: Final = 60.0

# The ceiling on one answer, and it is a ceiling rather than a budget:
# nothing is charged for room that goes unused, so the only thing a low
# number buys is a truncated answer.
#
# This product's largest schema needs more than four thousand: an
# audience, a dozen interests, three adverts and a form's questions, all
# written in Uzbek, which costs noticeably more tokens per sentence than
# English. An answer that runs past the ceiling stops mid-word, and what
# comes back is cut before the first field closes - which validates
# exactly like an empty answer: "audience: Field required; interests:
# Field required" and so on down the list. Nothing says the words "ran out
# of room".
DEFAULT_MAX_TOKENS: Final = 8_192

# What ``last_error`` says when the answer was cut off rather than wrong.
# The distinction is the whole of the diagnosis: one is a prompt to fix and
# the other is a ceiling to raise, and the two arrive looking identical.
TRUNCATED: Final = "the answer was cut off at the token ceiling"

# Asked once, and re-asked once with the validation error attached. A third
# attempt on the same prompt produces the same class of answer and costs
# another call.
MAX_ATTEMPTS: Final = 2

# How many of a wrong answer's top-level keys the log names. Enough to see
# that the fields arrived wrapped in another object, or not at all; an
# answer with forty keys at the top is its own diagnosis.
LOGGED_KEYS: Final = 10

# The package's own logger. stdlib, configured by whoever imports it -
# nothing here reads a setting or picks a handler.
logger = logging.getLogger(__name__)

# The SDK retries transport failures itself. Set to zero because retrying is
# the caller's decision here too: a Celery task can back off for a minute,
# and a person waiting on a wizard cannot.
SDK_RETRIES: Final = 0

# What, if anything, of a request is offered to the prompt cache.
#
# A named policy rather than a boolean, because "cache: true" answers the
# wrong question. What matters is *which part* is stable enough to be
# worth a cache breakpoint, and the answer is not the same for every call:
# a system prompt that is identical for every reader of a language is; the
# account digest underneath it changes on every question and never will be.
#
# ``"system"`` puts one breakpoint at the end of ``system`` and leaves
# ``system_tail`` outside it, and only when both are there.
# ``"instructions"`` marks ``system`` even alone: for a caller whose system
# prompt is nothing but instructions shared by every call and whose
# changing part is the message itself. ``"off"`` sends one system string and is what
# every deployment gets until somebody has measured that caching helps -
# see :meth:`ClaudeClient.count_tokens`, which is how that is measured.
CachePolicy = Literal["off", "system", "instructions"]

# What marks the end of the cached prefix. Anthropic's shortest-lived
# breakpoint, which is the right one here: the saving comes from questions
# arriving minutes apart, and a longer window costs more to write.
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

    # --- Lifecycle -------------------------------------------------------
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

    # --- Asking ----------------------------------------------------------
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
        """Ask for one answer shaped like ``schema``.

        The prompt arrives already rendered. Choosing what to ask is domain
        knowledge and lives above this package; all that happens here is
        making sure the answer can be trusted to have the right fields.

        ``system`` is the stable half of the instructions and ``system_tail``
        is whatever changes from call to call. Sent as one string unless
        this client was built with a cache policy, in which case the
        breakpoint goes between them - see :data:`CachePolicy`. A caller
        that passes only ``system`` is unaffected.

        ``images`` go before the prompt, each after its own label: Claude
        reads a picture-then-question message best, and a label is the
        only way the prompt can say which picture it means.

        Tokens from both attempts are added up, cache tokens included. The
        second attempt is not free, and a cost that only counted the
        successful call would make a drifting prompt look cheap. A call
        that fails carries the same figures on the exception (``spent``).
        """
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

            # Declined, which is neither wrong nor cut off. What comes with
            # a refusal need not fit the schema, so validating it like any
            # answer would report a dozen missing fields and ask again -
            # the same refusal, bought twice.
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

            # Cut off, not wrong. Asked here rather than left to the
            # validator below, which would report a truncated answer as a
            # dozen missing fields and send the model off to "fix" fields
            # it had already written.
            if answer.stop_reason == "max_tokens":
                last_error = TRUNCATED
                truncated += 1
                logger.warning(
                    "llm_answer_truncated",
                    extra={**said, "max_tokens": self._max_tokens},
                )
                # The whole conversation replaced, not appended to. Two
                # reasons, and the second is the one that would have bitten:
                # the partial answer is the thing that was too long and
                # handing it back invites the same length again, and an
                # appended user turn after a user turn is not a shape the
                # API is guaranteed to accept - roles are expected to
                # alternate, so a "be shorter" note tacked on would risk
                # turning a retry into a four hundred.
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
                # Said out loud, because the caller cannot see it and the
                # cost is not small: a second attempt roughly doubles both
                # the tokens and the wait, and the only thing that ends it
                # is knowing which field keeps missing. Silent, it is a
                # prompt drifting for weeks behind a spinner nobody can
                # explain.
                #
                # And with what actually came back beside it. "audience:
                # Field required" reads the same for an empty answer, for
                # fields wrapped inside a key nobody asked for, and for
                # prose where an object was due - three answers with three
                # different fixes, which only the keys and the blocks tell
                # apart.
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
                # Hand the model its own answer and what was wrong with it.
                # Re-asking from scratch loses the parts that were right.
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
        """Ask for one answer and read it as it is written.

        Free text, where :meth:`structured` forces a schema. The caller gets
        a sentence rather than data, which is why nothing downstream parses
        it - and why what does happen downstream is a gate that checks the
        sentence against what was put into it.

        ``history`` is ``(role, text)`` pairs, oldest first, already trimmed
        by whoever owns the conversation. Trimming here would put the memory
        policy inside a package that has no idea what a session is.

        ``max_tokens`` of nought means the client's own ceiling. A ceiling
        rather than a target either way: an answer long enough to hit it has
        already gone wrong, and cutting it mid-sentence is the visible half
        of that failure.

        ``system_tail`` is the half of the instructions that changes on
        every call. This is where caching earns most: a conversation sends
        the same instructions again on every question, and only what is
        below them moves.
        """
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
        """Ask for one answer that may look things up before it is written.

        :meth:`stream` with tools. ``run_tool`` is handed each call with its
        arguments already validated and returns the text the model reads;
        see :mod:`llmkit.conversation` for the rounds and their bound.

        ``max_tokens`` is per round, and a round that only calls a tool
        writes a few dozen of them.
        """
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

    # --- Transport -------------------------------------------------------
    def _send(
        self,
        *,
        messages: list[MessageParam],
        system: str,
        system_tail: str,
        output: OutputConfigParam,
    ) -> Message:
        """One request, with Anthropic's failures translated to ours.

        No tools and no ``tool_choice``: the schema travels as the answer's
        format, which every model with structured outputs accepts -
        including the ones that refuse to be forced to call a tool.
        """
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
        """The user turn: the prompt alone, or the pictures and then it.

        A bare string when there is no picture, which is what every caller
        before pictures sent and keeps the request byte-for-byte the same.
        """
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
        """The system prompt, as one string or as two blocks with a marker.

        ``omit`` rather than an empty string when there is nothing to say:
        an empty system prompt is still a system prompt, and the API
        charges for it.

        Two blocks only when this client was configured to cache and there
        is something on both sides of the line. A caller that filled one
        half alone has not said which of its text repeats and which is
        about one account, and a breakpoint placed on a guess is paid for
        at the write price and read back never.
        """
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

    # --- Measuring ------------------------------------------------------
    def count_tokens(
        self,
        *,
        prompt: str,
        system: str = "",
        system_tail: str = "",
        history: tuple[tuple[str, str], ...] = (),
        schema: type[BaseModel] | None = None,
    ) -> int:
        """How many input tokens this request would cost, without asking it.

        **The measurement the cost work has to start from.** Everything
        else here is a lever - caching, a cheaper model, a shorter context -
        and pulling one before knowing which part of a request is large is
        how a week is spent saving forty tokens. Anthropic counts this
        exactly, on the same tokeniser that will bill it, and the call is
        free.

        The arguments mirror :meth:`structured` and :meth:`stream` on
        purpose: a measurement of a request assembled differently from the
        request is a measurement of something else.
        """
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

    # --- Structured output ----------------------------------------------
    @staticmethod
    def _format_for(schema: type[BaseModel]) -> OutputConfigParam:
        """The schema, as the one shape the answer may take.

        Through the SDK's own ``transform_schema`` rather than as pydantic
        writes it, because the API insists on two things pydantic does not
        do. Every object is closed (``additionalProperties: false``), so an
        answer cannot put its fields inside a key nobody asked for. And the
        rules the API will not take - lengths, numeric bounds, list sizes
        past one - are moved into the field's description, where the model
        still reads them, instead of being sent as rules the request would
        be refused for. :meth:`structured` checks them afterwards, by
        validating against the model itself.
        """
        return {
            "format": {
                "type": "json_schema",
                "schema": anthropic.transform_schema(schema),
            }
        }

    @staticmethod
    def _payload(answer: Message) -> dict[str, Any]:
        """The answer's JSON object, or an empty dict.

        Empty rather than raising: an answer that is not an object - prose,
        a list, text cut off mid-string - is a schema mismatch like any
        other, and it should go through the same re-ask-once path instead
        of failing differently.
        """
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
        """What to say to an answer that ran out of room.

        Its own message rather than ``_correction``: nothing was wrong with
        the fields, so "fixing only these fields" names nothing, and the
        model's own partial answer is deliberately not handed back - it is
        the thing that was too long.
        """
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
    """Tokens written into the cache by this call, or nought.

    ``None`` is what the API sends when nothing was cached, and it is not
    the same as a zero that was measured - but for arithmetic it is, and a
    ledger that stored ``None`` would have to explain itself to every sum.
    """
    return int(usage.cache_creation_input_tokens or 0)


def _read(usage: Usage) -> int:
    """Tokens served out of the cache. Charged, and not in ``input_tokens``."""
    return int(usage.cache_read_input_tokens or 0)
