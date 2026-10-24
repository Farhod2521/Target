"""``ClaudeClient.converse``: rounds, look-ups, their bound, and the receipt."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import anthropic
import httpx
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from llmkit import ClaudeClient, ClaudeRateLimited, LLMError, Tool, ToolCall, ToolOutput
from llmkit.conversation import ROUND_BREAK
from llmkit.models import Pricing
from pydantic import BaseModel, Field


class Lookup(BaseModel):
    query: str = Field(min_length=2)


LOOKUP = Tool(name="lookup", description="Find a thing.", arguments=Lookup)


def said(
    *pieces: str,
    calls: tuple[tuple[str, dict[str, Any]], ...] = (),
    stop_reason: str = "",
) -> Any:
    """One scripted round: the text it streams and the calls it ends with."""
    content: list[Any] = [
        TextBlock.model_construct(type="text", text="".join(pieces), citations=None)
    ]
    content += [
        ToolUseBlock.model_construct(
            type="tool_use", id=f"call-{name}-{index}", name=name, input=arguments
        )
        for index, (name, arguments) in enumerate(calls)
    ]
    final = Message.model_construct(
        id="msg",
        type="message",
        role="assistant",
        model="claude-test",
        content=content,
        stop_reason=stop_reason or ("tool_use" if calls else "end_turn"),
        stop_sequence=None,
        usage=Usage.model_construct(
            input_tokens=1_000,
            output_tokens=100,
            cache_creation_input_tokens=None,
            cache_read_input_tokens=None,
        ),
    )
    return list(pieces), final


class FakeStream:
    def __init__(self, pieces: list[str], final: Any) -> None:
        self.text_stream = iter(pieces)
        self._final = final

    def get_final_message(self) -> Any:
        return self._final


class FakeMessages:
    def __init__(self, rounds: list[Any], *, error: Exception | None = None) -> None:
        self._rounds = rounds
        self._error = error
        self.requests: list[dict[str, Any]] = []

    @contextmanager
    def stream(self, **kwargs: Any) -> Iterator[FakeStream]:
        # A copy: the conversation appends to the same list between rounds.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        if self._error is not None:
            raise self._error
        pieces, final = self._rounds[len(self.requests) - 1]
        yield FakeStream(pieces, final)


class FakeAnthropic:
    def __init__(self, rounds: list[Any], *, error: Exception | None = None) -> None:
        self.messages = FakeMessages(rounds, error=error)

    def close(self) -> None:
        return None


class Desk:
    """A caller's runner that remembers what it was asked."""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def __call__(self, call: ToolCall) -> ToolOutput:
        self.calls.append(call)
        return ToolOutput(text="Found: 2 pages")


def client_for(rounds: list[Any], **kwargs: Any) -> tuple[ClaudeClient, FakeAnthropic]:
    fake = FakeAnthropic(rounds, **kwargs)
    client = ClaudeClient(
        api_key="k",
        model="claude-test",
        pricing=Pricing(
            input_per_mtok_minor=300_000,
            output_per_mtok_minor=1_500_000,
            currency="USD",
        ),
        client=fake,  # type: ignore[arg-type]
    )
    return client, fake


def test_an_answer_that_needs_nothing_is_one_round() -> None:
    client, fake = client_for([said("Salom", "!")])
    desk = Desk()

    stream = client.converse(prompt="Salom", tools=[LOOKUP], run_tool=desk)
    text = "".join(stream)

    assert text == "Salom!"
    assert stream.result.rounds == 1
    assert stream.result.tool_calls == 0
    assert desk.calls == []
    assert fake.messages.requests[0]["tools"][0]["name"] == "lookup"
    assert fake.messages.requests[0]["tool_choice"] is anthropic.omit


def test_a_look_up_is_run_and_its_result_goes_back_to_the_model() -> None:
    client, fake = client_for(
        [said(calls=(("lookup", {"query": "pages"}),)), said("Sizda 2 ta sahifa.")]
    )
    desk = Desk()

    stream = client.converse(prompt="Nechta page?", tools=[LOOKUP], run_tool=desk)
    text = "".join(stream)

    assert text == "Sizda 2 ta sahifa."
    assert [call.arguments for call in desk.calls] == [Lookup(query="pages")]
    second = fake.messages.requests[1]["messages"]
    assert second[-2]["role"] == "assistant"
    assert second[-1]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "call-lookup-0",
            "content": "Found: 2 pages",
            "is_error": False,
        }
    ]


def test_every_round_is_on_the_one_receipt() -> None:
    client, _ = client_for(
        [said(calls=(("lookup", {"query": "pages"}),)), said("Tayyor.")]
    )

    stream = client.converse(prompt="?", tools=[LOOKUP], run_tool=Desk())
    list(stream)

    assert stream.result.rounds == 2
    assert stream.result.tool_calls == 1
    assert stream.result.input_tokens == 2_000
    assert stream.result.output_tokens == 200
    # 2 000 x 300 000 + 200 x 1 500 000, per million.
    assert stream.result.cost_minor == 900
    assert stream.result.currency == "USD"


def test_a_round_that_ran_out_of_room_ends_the_answer_and_is_counted() -> None:
    client, fake = client_for(
        [
            said(calls=(("lookup", {"query": "pages"}),)),
            said("Birinchi sahna, ikkinchi", stop_reason="max_tokens"),
        ]
    )

    stream = client.converse(prompt="?", tools=[LOOKUP], run_tool=Desk())
    list(stream)

    assert stream.result.truncated == 1
    assert len(fake.messages.requests) == 2


def test_text_on_both_sides_of_a_look_up_does_not_run_together() -> None:
    client, _ = client_for(
        [said("Tekshiraman.", calls=(("lookup", {"query": "pages"}),)), said("Ikki.")]
    )

    text = "".join(client.converse(prompt="?", tools=[LOOKUP], run_tool=Desk()))

    assert text == f"Tekshiraman.{ROUND_BREAK}Ikki."


def test_arguments_that_do_not_fit_are_refused_without_running_the_tool() -> None:
    client, fake = client_for(
        [said(calls=(("lookup", {"query": "x"}),)), said("Topilmadi.")]
    )
    desk = Desk()

    list(client.converse(prompt="?", tools=[LOOKUP], run_tool=desk))

    assert desk.calls == []
    answer = fake.messages.requests[1]["messages"][-1]["content"][0]
    assert answer["is_error"] is True
    assert answer["content"].startswith("Invalid arguments: query")


def test_a_tool_nobody_declared_is_refused() -> None:
    client, fake = client_for([said(calls=(("delete_all", {}),)), said("Yo'q.")])
    desk = Desk()

    list(client.converse(prompt="?", tools=[LOOKUP], run_tool=desk))

    assert desk.calls == []
    assert fake.messages.requests[1]["messages"][-1]["content"][0]["is_error"]


def test_the_last_round_may_not_look_anything_up() -> None:
    """A model that keeps asking is stopped by the request, not by trust."""
    looking = said(calls=(("lookup", {"query": "again"}),))
    client, fake = client_for([looking, looking, said("Bor ma'lumot bilan.")])
    desk = Desk()

    stream = client.converse(prompt="?", tools=[LOOKUP], run_tool=desk, max_rounds=3)
    list(stream)

    choices = [request["tool_choice"] for request in fake.messages.requests]
    assert choices == [anthropic.omit, anthropic.omit, {"type": "none"}]
    assert len(desk.calls) == 2
    assert stream.result.rounds == 3


def test_the_receipt_is_not_there_before_the_answer_is_read() -> None:
    client, _ = client_for([said("Salom")])

    stream = client.converse(prompt="?", tools=[LOOKUP], run_tool=Desk())

    with pytest.raises(LLMError):
        _ = stream.result


def test_a_rate_limit_arrives_as_the_packages_own_error() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.RateLimitError(
        "slow down", response=httpx.Response(429, request=request), body=None
    )
    client, _ = client_for([], error=error)

    with pytest.raises(ClaudeRateLimited):
        list(client.converse(prompt="?", tools=[LOOKUP], run_tool=Desk()))
