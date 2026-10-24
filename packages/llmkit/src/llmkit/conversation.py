"""An answer that may look things up before it is written, read as it arrives."""

import time
from collections.abc import Generator, Iterator, Sequence
from typing import Any, Final

import anthropic
from anthropic.types import Message, MessageParam, ToolResultBlockParam, ToolUseBlock

from llmkit.errors import LLMError
from llmkit.models import LLMResult, Pricing
from llmkit.tools import Tool, ToolOutput, ToolRunner, checked
from llmkit.transport import translated

DEFAULT_MAX_ROUNDS: Final = 4

ROUND_BREAK: Final = "\n\n"

NOT_FINISHED: Final = "the stream has not been read to the end yet"

_NO_TOOLS: Final[Any] = {"type": "none"}


class ToolStream:
    """One answer across however many rounds it took. Iterate, then ``result``."""

    def __init__(
        self,
        *,
        client: anthropic.Anthropic,
        model: str,
        max_tokens: int,
        system: Any,
        messages: list[MessageParam],
        tools: Sequence[Tool],
        run_tool: ToolRunner,
        pricing: Pricing,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        prompt_name: str = "",
        prompt_version: str = "",
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._system = system
        self._messages = list(messages)
        self._tools = {tool.name: tool for tool in tools}
        self._params = [tool.as_param() for tool in tools]
        self._run_tool = run_tool
        self._pricing = pricing
        self._max_rounds = max(1, max_rounds)
        self._prompt_name = prompt_name
        self._prompt_version = prompt_version
        self._usage = [0, 0, 0, 0]
        self._rounds = 0
        self._calls = 0
        self._truncated = 0
        self._spoke = False
        self._result: LLMResult[str] | None = None

    def __iter__(self) -> Iterator[str]:
        started = time.monotonic()
        collected: list[str] = []
        for number in range(1, self._max_rounds + 1):
            final = yield from self._round(
                collected=collected, closing=number == self._max_rounds
            )
            calls = [
                block for block in final.content if isinstance(block, ToolUseBlock)
            ]
            if final.stop_reason != "tool_use" or not calls:
                break
            self._messages.append({"role": "assistant", "content": final.content})
            self._messages.append(
                {"role": "user", "content": [self._answer(block) for block in calls]}
            )
        self._result = self._receipt(
            text="".join(collected), latency_ms=_since(started)
        )

    @property
    def result(self) -> LLMResult[str]:
        """What the whole answer cost. Only after it has been read out."""
        if self._result is None:
            raise LLMError(NOT_FINISHED)
        return self._result

    @property
    def is_finished(self) -> bool:
        return self._result is not None

    def _round(
        self, *, collected: list[str], closing: bool
    ) -> Generator[str, None, Message]:
        """One request: stream its text, then return the finished message."""
        self._rounds += 1
        gap = self._spoke
        with (
            translated(),
            self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system,
                messages=self._messages,
                tools=self._params,
                tool_choice=_NO_TOOLS if closing else anthropic.omit,
            ) as stream,
        ):
            for piece in stream.text_stream:
                if gap:
                    collected.append(ROUND_BREAK)
                    yield ROUND_BREAK
                    gap = False
                self._spoke = True
                collected.append(piece)
                yield piece
            final: Message = stream.get_final_message()
        self._count(final)
        return final

    def _answer(self, block: ToolUseBlock) -> ToolResultBlockParam:
        """Run one call through the caller, or say why it was not run."""
        self._calls += 1
        call = checked(
            tools=self._tools, call_id=block.id, name=block.name, raw=block.input
        )
        output = call if isinstance(call, ToolOutput) else self._run_tool(call)
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": output.text,
            "is_error": output.is_error,
        }

    def _count(self, final: Message) -> None:
        usage = final.usage
        self._usage[0] += usage.input_tokens
        self._usage[1] += usage.output_tokens
        self._usage[2] += int(usage.cache_creation_input_tokens or 0)
        self._usage[3] += int(usage.cache_read_input_tokens or 0)
        self._truncated += int(final.stop_reason == "max_tokens")

    def _receipt(self, *, text: str, latency_ms: int) -> LLMResult[str]:
        read, written, written_cache, served = self._usage
        return LLMResult(
            value=text,
            input_tokens=read,
            output_tokens=written,
            cost_micros=self._pricing.cost_micros(
                input_tokens=read,
                output_tokens=written,
                cache_write_tokens=written_cache,
                cache_read_tokens=served,
            ),
            currency=self._pricing.currency,
            latency_ms=latency_ms,
            prompt_name=self._prompt_name,
            prompt_version=self._prompt_version,
            model=self._model,
            cache_write_tokens=written_cache,
            cache_read_tokens=served,
            rounds=self._rounds,
            tool_calls=self._calls,
            truncated=self._truncated,
        )


def _since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


__all__ = ["DEFAULT_MAX_ROUNDS", "ROUND_BREAK", "ToolStream"]
