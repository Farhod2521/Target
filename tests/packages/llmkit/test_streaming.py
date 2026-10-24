"""``ClaudeClient.stream``: the pieces, the receipt, and the failures."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import anthropic
import httpx
import pytest
from llmkit import ClaudeClient, ClaudeRateLimited, ClaudeTemporaryError, LLMError
from llmkit.models import Pricing


class FakeStream:
    def __init__(self, pieces: list[str], *, usage: Any, stop_reason: str) -> None:
        self.text_stream = iter(pieces)
        self._usage = usage
        self._stop_reason = stop_reason

    def get_final_message(self) -> Any:
        return type(
            "Message", (), {"usage": self._usage, "stop_reason": self._stop_reason}
        )()


class FakeMessages:
    def __init__(
        self,
        pieces: list[str],
        *,
        error: Exception | None = None,
        stop_reason: str = "end_turn",
    ) -> None:
        self._pieces = pieces
        self._error = error
        self._stop_reason = stop_reason
        self.kwargs: dict[str, Any] = {}

    @contextmanager
    def stream(self, **kwargs: Any) -> Iterator[FakeStream]:
        self.kwargs = kwargs
        if self._error is not None:
            raise self._error
        usage = type(
            "Usage",
            (),
            {
                "input_tokens": 1_000,
                "output_tokens": 500,
                # ``None`` rather than nought, which is what the API sends
                # on a call that used no cache at all.
                "cache_creation_input_tokens": None,
                "cache_read_input_tokens": None,
            },
        )()
        yield FakeStream(self._pieces, usage=usage, stop_reason=self._stop_reason)


class FakeAnthropic:
    def __init__(
        self,
        pieces: list[str],
        *,
        error: Exception | None = None,
        stop_reason: str = "end_turn",
    ) -> None:
        self.messages = FakeMessages(pieces, error=error, stop_reason=stop_reason)

    def close(self) -> None:
        return None


def http(status: int) -> httpx.Response:
    """A real response: the SDK's errors read ``.request`` off it."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status, request=request, json={})


def client(*pieces: str, error: Exception | None = None) -> ClaudeClient:
    return ClaudeClient(
        api_key="x",
        model="claude-test",
        pricing=Pricing(
            input_per_mtok_minor=300, output_per_mtok_minor=1_500, currency="USD"
        ),
        client=FakeAnthropic(list(pieces), error=error),  # type: ignore[arg-type]
    )


def test_the_pieces_arrive_in_order() -> None:
    stream = client("Sa", "lom", " dunyo").stream(prompt="salom")

    assert list(stream) == ["Sa", "lom", " dunyo"]


def test_an_answer_that_ran_out_of_room_says_so_on_its_receipt() -> None:
    fake = FakeAnthropic(["Birinchi sahna, ikkinchi"], stop_reason="max_tokens")
    stream = ClaudeClient(
        api_key="x",
        model="claude-test",
        pricing=Pricing(
            input_per_mtok_minor=300, output_per_mtok_minor=1_500, currency="USD"
        ),
        client=fake,  # type: ignore[arg-type]
    ).stream(prompt="ssenariy")
    list(stream)

    assert stream.result.truncated == 1


def test_a_finished_answer_is_not_counted_as_cut() -> None:
    stream = client("Tayyor.").stream(prompt="?")
    list(stream)

    assert stream.result.truncated == 0


def test_the_receipt_is_only_readable_once_the_stream_is_read() -> None:
    """A cost of nought written to the ledger looks like a call that never
    happened, and the month's total is what the ceiling compares against."""
    stream = client("javob").stream(prompt="salom")

    with pytest.raises(LLMError):
        _ = stream.result

    list(stream)

    assert stream.result.value == "javob"
    assert stream.result.input_tokens == 1_000
    # One division at the end, not one per side: rounding each separately
    # would lose a fraction of a cent twice on every call.
    assert stream.result.cost_minor == (1_000 * 300 + 500 * 1_500) // 1_000_000


def test_history_becomes_alternating_messages() -> None:
    fake = FakeAnthropic([])
    talker = ClaudeClient(api_key="x", model="m", client=fake)  # type: ignore[arg-type]

    list(
        talker.stream(
            prompt="uchinchi",
            history=(("user", "birinchi"), ("assistant", "ikkinchi")),
        )
    )

    assert fake.messages.kwargs["messages"] == [
        {"role": "user", "content": "birinchi"},
        {"role": "assistant", "content": "ikkinchi"},
        {"role": "user", "content": "uchinchi"},
    ]


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (
            anthropic.RateLimitError("slow", response=http(429), body=None),
            ClaudeRateLimited,
        ),
        (
            anthropic.APIConnectionError(
                request=httpx.Request("POST", "https://api.anthropic.com/")
            ),
            ClaudeTemporaryError,
        ),
    ],
)
def test_a_streamed_failure_is_translated_like_a_structured_one(
    raised: Exception, expected: type[Exception]
) -> None:
    """One translation for both call shapes.

    The day a streamed rate limit raised something the structured path did
    not, a caller written against one would be wrong about the other.
    """
    with pytest.raises(expected):
        list(client(error=raised).stream(prompt="salom"))
