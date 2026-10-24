"""Asking Claude for a shape, and what happens when the shape is wrong.

No network and no key: the SDK client is replaced with a scripted stand-in.
What is being tested is the contract around the model - that the schema is
sent as the answer's format and not as a tool, that a mismatched answer is
re-asked exactly once and a refusal is not, that every attempt is paid for
and a failure says what it cost, and that no Anthropic exception class
escapes as itself.
"""

import base64
import json
import logging
from collections.abc import Iterator
from typing import Any

import anthropic
import httpx
import pytest
from llmkit.client import DEFAULT_MAX_TOKENS, MAX_ATTEMPTS, ClaudeClient
from llmkit.errors import (
    ClaudeAuthError,
    ClaudeRateLimited,
    ClaudeRefused,
    ClaudeSpendLimit,
    ClaudeTemporaryError,
    LLMError,
    StructuredOutputError,
)
from llmkit.models import Image, Pricing
from pydantic import BaseModel, Field


class Draft(BaseModel):
    """An audience draft, in the shape the domain asked for."""

    age_min: int = Field(ge=18)
    age_max: int = Field(le=65)
    reasoning: str = ""


class Drafts(BaseModel):
    """Several of them - the shape of every real answer here: a list of
    objects, bounded at both ends."""

    items: list[Draft] = Field(min_length=6, max_length=12)


class _Usage:
    """What the API reports about one answer, all four figures of it.

    The two cache counts are ``None`` on an uncached call, which is what
    the API actually sends - not nought. The difference matters: a caller
    that treated ``None`` as a number would add it to a total.
    """

    def __init__(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_creation_input_tokens: int | None = None,
        cache_read_input_tokens: int | None = None,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


def _http(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    """A real response, because the SDK's errors read `.request` off it."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status, request=request, headers=headers or {}, json={})


class _Answer:
    def __init__(
        self,
        payload: Any,
        *,
        tokens: int = 10,
        stop_reason: str = "end_turn",
    ) -> None:
        block = _json_block(payload) if payload is not None else _prose_block()
        self.content = [block]
        self.usage = _Usage(tokens, tokens)
        # What ended the answer. ``max_tokens`` and ``refusal`` are the two
        # that matter here: the first stops mid-word, and the second comes
        # with whatever had been written, which need not fit anything.
        self.stop_reason = stop_reason


def _json_block(payload: Any) -> anthropic.types.TextBlock:
    """The answer as the API sends it under a JSON format: one text block."""
    return anthropic.types.TextBlock(text=json.dumps(payload), type="text")


def _prose_block() -> anthropic.types.TextBlock:
    """What a model that ignored the format would send back."""
    return anthropic.types.TextBlock(text="Here is my answer:", type="text")


class _Messages:
    def __init__(self, answers: list[Any]) -> None:
        self._answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        answer = self._answers.pop(0) if self._answers else self._answers
        if isinstance(answer, Exception):
            raise answer
        return answer


class _SDK:
    def __init__(self, *answers: Any) -> None:
        self.messages = _Messages(list(answers))

    def close(self) -> None:  # pragma: no cover - nothing to close
        pass


def client_for(*answers: Any, pricing: Pricing | None = None) -> ClaudeClient:
    return ClaudeClient(
        api_key="unused",
        model="claude-test",
        pricing=pricing,
        client=_SDK(*answers),  # type: ignore[arg-type]
    )


def asked(*answers: Any) -> tuple[ClaudeClient, _SDK]:
    """A client and the stand-in behind it, for tests about the request."""
    sdk = _SDK(*answers)
    client = ClaudeClient(
        api_key="unused",
        model="claude-test",
        client=sdk,  # type: ignore[arg-type]
    )
    return client, sdk


def objects_in(schema: Any) -> Iterator[dict[str, Any]]:
    """Every object definition in a JSON schema, the nested ones included."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from objects_in(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from objects_in(value)


GOOD = {"age_min": 25, "age_max": 45, "reasoning": "Tushlik qiladiganlar"}
BAD = {"age_min": 12, "age_max": 45}


# --- Running out of room -------------------------------------------------
def test_an_answer_cut_off_is_not_reported_as_a_missing_field(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The two failures need different fixes and otherwise look identical.

    An answer cut off before its first field closed arrives as an empty
    one, and an empty one validates as every field being absent. So a
    ceiling that is too low reads as a prompt that has stopped answering -
    and the ceiling, being the thing nobody looks at, stays too low.
    """
    truncated = _Answer(GOOD, stop_reason="max_tokens")

    with (
        caplog.at_level(logging.WARNING, logger="llmkit.client"),
        pytest.raises(StructuredOutputError) as raised,
    ):
        client_for(truncated, truncated).structured(prompt="salom", schema=Draft)

    assert "cut off" in str(raised.value)
    events = [record.message for record in caplog.records]
    assert events == ["llm_answer_truncated", "llm_answer_truncated"]
    assert caplog.records[0].max_tokens == DEFAULT_MAX_TOKENS


def test_the_second_ask_says_be_shorter_rather_than_naming_fields() -> None:
    """Nothing was wrong with the fields, so a correction listing them
    would send the model to fix what it never got to write."""
    client, sdk = asked(_Answer(GOOD, stop_reason="max_tokens"), _Answer(GOOD))

    result = client.structured(prompt="salom", schema=Draft)

    assert result.attempts == 2
    # One user turn, not two. The API expects roles to alternate, so a
    # "be shorter" note appended after the prompt's own user turn is a
    # request shape that can be refused outright - which would turn every
    # truncated answer into a failed call rather than a second try.
    sent = sdk.messages.calls[1]["messages"]
    assert [message["role"] for message in sent] == ["user"]
    assert "salom" in sent[0]["content"]
    assert "shorter" in sent[0]["content"]
    assert "did not fit" not in sent[0]["content"]


def test_a_ceiling_high_enough_for_the_largest_answer_is_the_default() -> None:
    """Room costs nothing that goes unused - only a low number buys
    anything, and what it buys is a truncated answer."""
    client, sdk = asked(_Answer(GOOD))

    client.structured(prompt="salom", schema=Draft)

    assert sdk.messages.calls[0]["max_tokens"] == DEFAULT_MAX_TOKENS
    assert DEFAULT_MAX_TOKENS >= 8_192


# --- The happy path ------------------------------------------------------
def test_the_answer_comes_back_as_the_schema_not_a_dict() -> None:
    """A dict would make every caller re-validate, and most would not."""
    result = client_for(_Answer(GOOD)).structured(prompt="salom", schema=Draft)

    assert isinstance(result.value, Draft)
    assert result.value.age_min == 25


def test_the_schema_is_sent_as_the_answers_format_and_not_as_a_tool() -> None:
    """A forced tool is refused outright by some models, and its arguments
    are not checked against the schema anyway - an answer with none of the
    fields comes back as an empty call."""
    client, sdk = asked(_Answer(GOOD))

    client.structured(prompt="salom", schema=Draft)

    sent = sdk.messages.calls[0]
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["output_config"]["format"]["schema"]["properties"]["age_min"]
    assert "tools" not in sent
    assert "tool_choice" not in sent


def test_every_object_sent_is_closed() -> None:
    """``additionalProperties: false`` at every level, nested ones too: an
    answer cannot put its fields inside a key nobody asked for, which is
    one of the two ways an answer arrives with every field missing."""
    client, sdk = asked(_Answer({"items": [GOOD] * 6}))

    client.structured(prompt="salom", schema=Drafts)

    found = list(objects_in(sdk.messages.calls[0]["output_config"]))
    assert len(found) >= 2
    assert all(item.get("additionalProperties") is False for item in found)


def test_rules_the_api_refuses_are_said_rather_than_sent() -> None:
    """The API refuses a schema carrying lengths and bounds, so they leave
    the schema - and stay in the description, which is what the model reads
    while it writes the field."""
    client, sdk = asked(_Answer({"items": [GOOD] * 6}))

    client.structured(prompt="salom", schema=Drafts)

    text = json.dumps(sdk.messages.calls[0]["output_config"])
    for rule in ("minimum", "maximum", "minItems", "maxItems"):
        assert f'"{rule}":' not in text, rule
    assert "minimum: 18" in text
    assert "maxItems: 12" in text


def test_a_rule_the_api_does_not_hold_is_still_held_here() -> None:
    """Five items where six is the least: the API has no way to refuse it,
    so the validator does, and the model is asked once more."""
    five, six = {"items": [GOOD] * 5}, {"items": [GOOD] * 6}

    result = client_for(_Answer(five), _Answer(six)).structured(
        prompt="salom", schema=Drafts
    )

    assert result.attempts == 2
    assert len(result.value.items) == 6


def test_an_empty_system_prompt_is_not_sent() -> None:
    """An empty system prompt is still a system prompt, and it is billed."""
    client, sdk = asked(_Answer(GOOD))

    client.structured(prompt="salom", schema=Draft)

    assert isinstance(sdk.messages.calls[0]["system"], anthropic.Omit)


def test_the_prompt_version_travels_with_the_result() -> None:
    """It is written to LLMCall; "latest" in a column ages into nothing."""
    result = client_for(_Answer(GOOD)).structured(
        prompt="salom", schema=Draft, prompt_name="audience", prompt_version="v3"
    )

    assert (result.prompt_name, result.prompt_version) == ("audience", "v3")
    assert result.model == "claude-test"


def test_latency_is_measured_not_guessed() -> None:
    result = client_for(_Answer(GOOD)).structured(prompt="salom", schema=Draft)

    assert result.latency_ms >= 0


# --- Getting it wrong ----------------------------------------------------
def test_a_wrong_answer_is_re_asked_once() -> None:
    """Re-asked with the error attached, so the right parts are not lost."""
    client, sdk = asked(_Answer(BAD), _Answer(GOOD))

    result = client.structured(prompt="salom", schema=Draft)

    assert result.attempts == 2
    assert len(sdk.messages.calls) == 2
    # The second request carries the first answer and what was wrong.
    follow_up = sdk.messages.calls[1]["messages"]
    assert len(follow_up) == 3
    assert json.loads(follow_up[1]["content"]) == BAD
    assert "age_min" in follow_up[2]["content"]
    # And asks for the shape it was given, not for a tool it was not.
    assert "tool" not in follow_up[2]["content"]


def test_a_re_ask_says_out_loud_which_field_was_wrong(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The second attempt is the largest single thing in this package's
    latency and its cost, and nothing above can see it - the caller gets
    one result either way - so the only way anybody learns that a prompt
    has started missing a field is if this line is written."""
    with caplog.at_level(logging.WARNING, logger="llmkit.client"):
        client_for(_Answer(BAD), _Answer(GOOD)).structured(
            prompt="salom", schema=Draft, prompt_name="launch_draft"
        )

    record = next(r for r in caplog.records if r.message == "llm_answer_invalid")
    assert record.prompt_name == "launch_draft"  # type: ignore[attr-defined]
    assert record.attempt == 1  # type: ignore[attr-defined]
    assert "age_min" in record.problem  # type: ignore[attr-defined]


def test_a_wrong_answer_says_what_actually_came_back(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ "audience: Field required" reads the same for an empty answer, for
    fields wrapped in a key nobody asked for, and for prose - three answers
    with three fixes, and the line is what carries the difference between
    them."""
    wrapped = {"answer": GOOD}

    with caplog.at_level(logging.WARNING, logger="llmkit.client"):
        client_for(_Answer(wrapped), _Answer(GOOD)).structured(
            prompt="salom", schema=Draft
        )

    record = next(r for r in caplog.records if r.message == "llm_answer_invalid")
    assert record.keys == ["answer"]  # type: ignore[attr-defined]
    assert record.blocks == ["text"]  # type: ignore[attr-defined]
    assert record.stop_reason == "end_turn"  # type: ignore[attr-defined]
    assert record.output_tokens == 10  # type: ignore[attr-defined]


def test_two_wrong_answers_raise_rather_than_settling() -> None:
    """ "Approximately right" targeting reaches the provider and spends money."""
    with pytest.raises(StructuredOutputError) as caught:
        client_for(_Answer(BAD), _Answer(BAD)).structured(prompt="s", schema=Draft)

    assert caught.value.schema == "Draft"


def test_it_never_asks_a_third_time() -> None:
    """A third attempt on the same prompt buys the same class of answer."""
    client, sdk = asked(_Answer(BAD), _Answer(BAD), _Answer(GOOD))

    with pytest.raises(StructuredOutputError):
        client.structured(prompt="s", schema=Draft)

    assert len(sdk.messages.calls) == MAX_ATTEMPTS


def test_an_answer_that_is_not_json_is_treated_as_a_mismatch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Prose instead of an object goes through the same re-ask, not a crash,
    and the line says nothing arrived rather than naming keys."""
    with caplog.at_level(logging.WARNING, logger="llmkit.client"):
        result = client_for(_Answer(None), _Answer(GOOD)).structured(
            prompt="s", schema=Draft
        )

    assert result.attempts == 2
    record = next(r for r in caplog.records if r.message == "llm_answer_invalid")
    assert record.keys == []  # type: ignore[attr-defined]


def test_both_attempts_are_paid_for() -> None:
    """A cost that counted only the successful call hides a drifting prompt."""
    pricing = Pricing(
        input_per_mtok_minor=300, output_per_mtok_minor=1500, currency="USD"
    )
    result = client_for(_Answer(BAD), _Answer(GOOD), pricing=pricing).structured(
        prompt="s", schema=Draft
    )

    assert result.input_tokens == 20
    assert result.output_tokens == 20


def test_a_failure_says_what_it_cost() -> None:
    """Two answers were written and paid for. A ledger recording the call
    that failed as costing nothing would make the dearest failures the
    cheapest-looking rows in it."""
    pricing = Pricing(
        input_per_mtok_minor=1_000_000, output_per_mtok_minor=2_000_000, currency="USD"
    )

    with pytest.raises(StructuredOutputError) as caught:
        client_for(_Answer(BAD), _Answer(BAD), pricing=pricing).structured(
            prompt="s", schema=Draft
        )

    spent = caught.value.spent
    assert (spent.input_tokens, spent.output_tokens) == (20, 20)
    assert spent.cost_minor == pricing.cost_minor(input_tokens=20, output_tokens=20)
    assert spent.cost_minor > 0


# --- Declining -----------------------------------------------------------
def test_a_refusal_is_not_asked_again(caplog: pytest.LogCaptureFixture) -> None:
    """What comes with a refusal need not fit the schema. Validated, it
    would be reported as a dozen missing fields and asked again - the same
    refusal, bought twice."""
    client, sdk = asked(_Answer({}, stop_reason="refusal"), _Answer(GOOD))

    with (
        caplog.at_level(logging.WARNING, logger="llmkit.client"),
        pytest.raises(ClaudeRefused) as caught,
    ):
        client.structured(prompt="s", schema=Draft, prompt_name="launch_draft")

    assert len(sdk.messages.calls) == 1
    assert caught.value.attempts == 1
    assert caught.value.spent.output_tokens == 10
    assert [record.message for record in caplog.records] == ["llm_answer_refusal"]


def test_a_refusal_is_one_of_ours() -> None:
    """Caught with the rest of the family by a caller that only knows it."""
    with pytest.raises(LLMError):
        client_for(_Answer({}, stop_reason="refusal")).structured(
            prompt="s", schema=Draft
        )


# --- Failures ------------------------------------------------------------
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        pytest.param(
            anthropic.AuthenticationError("bad key", response=_http(401), body=None),
            ClaudeAuthError,
            id="bad-key",
        ),
        pytest.param(
            anthropic.APITimeoutError(request=_http(408).request),
            ClaudeTemporaryError,
            id="timeout",
        ),
        pytest.param(
            anthropic.InternalServerError("boom", response=_http(500), body=None),
            ClaudeTemporaryError,
            id="5xx",
        ),
        pytest.param(
            anthropic.BadRequestError("our bug", response=_http(400), body=None),
            LLMError,
            id="our-bug",
        ),
    ],
)
def test_an_sdk_failure_arrives_as_ours(failure: Exception, expected: type) -> None:
    """A service catching anthropic.RateLimitError knows the SDK. It must not."""
    with pytest.raises(expected):
        client_for(failure).structured(prompt="s", schema=Draft)


def test_a_rate_limit_says_how_long_to_wait() -> None:
    failure = anthropic.RateLimitError(
        "slow down", response=_http(429, {"retry-after": "30"}), body=None
    )

    with pytest.raises(ClaudeRateLimited) as caught:
        client_for(failure).structured(prompt="s", schema=Draft)

    assert caught.value.retry_after_seconds == 30


@pytest.mark.parametrize(
    "failure",
    [
        anthropic.APIStatusError("billing", response=_http(402), body=None),
        anthropic.BadRequestError(
            "You have reached your specified workspace API usage limits.",
            response=_http(400),
            body=None,
        ),
        anthropic.BadRequestError(
            "Your credit balance is too low to access the Anthropic API.",
            response=_http(400),
            body=None,
        ),
    ],
)
def test_a_spent_limit_is_told_apart_from_a_bad_request(failure: Exception) -> None:
    """Nothing answers until someone raises the limit: not a bug, not a retry."""
    with pytest.raises(ClaudeSpendLimit):
        client_for(failure).structured(prompt="s", schema=Draft)


def test_an_auth_failure_is_not_retried() -> None:
    """Retrying a bad key is how it gets rate-limited as well as invalid."""
    client, sdk = asked(
        anthropic.AuthenticationError("bad key", response=_http(401), body=None)
    )

    with pytest.raises(ClaudeAuthError):
        client.structured(prompt="s", schema=Draft)

    assert len(sdk.messages.calls) == 1


# --- The system prompt, in one piece or two --------------------------
#
# The seam is where a cache breakpoint can go. Whether one is placed there
# is this client's configuration, and everything else about the request is
# identical either way.
def caching_client(*answers: Any, caching: str = "system") -> ClaudeClient:
    return ClaudeClient(
        api_key="unused",
        model="claude-test",
        caching=caching,  # type: ignore[arg-type]
        client=_SDK(*answers),  # type: ignore[arg-type]
    )


def sent(client: ClaudeClient) -> dict[str, Any]:
    return client._client.messages.calls[0]  # type: ignore[attr-defined]


def test_without_caching_the_two_halves_arrive_as_one_string() -> None:
    """The behaviour every deployment gets until somebody measures.

    A caller that splits its system prompt must not thereby change what
    the model is told - only where a marker could be put.
    """
    client = client_for(_Answer(GOOD))

    client.structured(
        prompt="salom", schema=Draft, system="Instructions", system_tail="Context"
    )

    assert sent(client)["system"] == "Instructions\n\nContext"


def test_with_caching_the_stable_half_is_marked_and_the_rest_is_not() -> None:
    client = caching_client(_Answer(GOOD))

    client.structured(
        prompt="salom", schema=Draft, system="Instructions", system_tail="Context"
    )

    blocks = sent(client)["system"]
    assert blocks[0]["text"] == "Instructions"
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["text"] == "Context"
    assert "cache_control" not in blocks[1]


def test_one_half_alone_is_not_marked() -> None:
    """A caller that filled one half has not said which of its text
    repeats and which is about one account. The weekly report's whole
    system prompt is the week it is about: a breakpoint placed on it is
    paid for at the write price and read back never."""
    client = caching_client(_Answer(GOOD))

    client.structured(prompt="salom", schema=Draft, system="This week: 140 USD")

    assert sent(client)["system"] == "This week: 140 USD"


def test_instructions_alone_are_marked_when_the_client_says_so() -> None:
    """A caller whose system prompt is only shared instructions keeps what
    changes in the message, after the mark."""
    client = caching_client(_Answer(GOOD), caching="instructions")

    client.structured(prompt="this video", schema=Draft, system="Instructions")

    assert sent(client)["system"] == [
        {"type": "text", "text": "Instructions", "cache_control": {"type": "ephemeral"}}
    ]


def test_a_tail_alone_is_not_marked_either() -> None:
    client = caching_client(_Answer(GOOD))

    client.structured(prompt="salom", schema=Draft, system_tail="Context")

    assert sent(client)["system"] == "Context"


def test_an_empty_system_prompt_is_omitted_rather_than_sent_empty() -> None:
    """An empty system prompt is still a system prompt, and is charged."""
    client = caching_client(_Answer(GOOD))

    client.structured(prompt="salom", schema=Draft)

    assert sent(client)["system"] is anthropic.omit


# --- What a cached call reports about itself -------------------------
def test_cache_tokens_are_carried_into_the_result() -> None:
    """They are not in ``input_tokens`` and would otherwise be lost.

    The ledger's monthly ceiling is a sum over the cost built from these,
    so a result that dropped them would make a cached month look free.
    """
    answer = _Answer(GOOD)
    answer.usage = _Usage(
        10, 10, cache_creation_input_tokens=400, cache_read_input_tokens=1_800
    )

    result = client_for(answer).structured(prompt="salom", schema=Draft)

    assert result.cache_write_tokens == 400
    assert result.cache_read_tokens == 1_800


def test_a_call_that_used_no_cache_reports_nought_rather_than_nothing() -> None:
    result = client_for(_Answer(GOOD)).structured(prompt="salom", schema=Draft)

    assert result.cache_write_tokens == 0
    assert result.cache_read_tokens == 0


def test_an_answer_that_ran_out_of_room_is_counted_as_such() -> None:
    """Beside ``attempts``, because the two have different fixes.

    A wrong answer is a prompt to correct; a cut-off one is a ceiling to
    raise. They cost the same and read the same in a token average.
    """
    result = client_for(
        _Answer(GOOD, stop_reason="max_tokens"), _Answer(GOOD)
    ).structured(prompt="salom", schema=Draft)

    assert result.truncated == 1
    assert result.attempts == 2


def test_an_ordinary_answer_was_not_cut_off() -> None:
    assert (
        client_for(_Answer(GOOD)).structured(prompt="salom", schema=Draft).truncated
        == 0
    )


# --- Measuring before optimising -------------------------------------
class _Counted:
    def __init__(self, tokens: int) -> None:
        self.input_tokens = tokens


def test_counting_tokens_assembles_the_request_the_same_way() -> None:
    """A measurement of a differently-built request measures something else."""
    client = caching_client()
    seen: list[dict[str, Any]] = []
    client._client.messages.count_tokens = (  # type: ignore[attr-defined]
        lambda **kwargs: seen.append(kwargs) or _Counted(1_234)
    )

    counted = client.count_tokens(
        prompt="salom", system="Instructions", system_tail="Context"
    )

    assert counted == 1_234
    assert seen[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert seen[0]["messages"][-1]["content"] == "salom"


def test_a_schema_is_counted_as_the_format_it_is_sent_as() -> None:
    """The same shape as the request, or the count is of another request."""
    client = caching_client()
    seen: list[dict[str, Any]] = []
    client._client.messages.count_tokens = (  # type: ignore[attr-defined]
        lambda **kwargs: seen.append(kwargs) or _Counted(1)
    )

    client.count_tokens(prompt="salom", schema=Draft)

    assert seen[0]["output_config"]["format"]["type"] == "json_schema"
    assert "tools" not in seen[0]


# --- Pictures ------------------------------------------------------------
def test_a_call_without_pictures_sends_the_prompt_as_one_string() -> None:
    client, sdk = asked(_Answer(GOOD))

    client.structured(prompt="salom", schema=Draft)

    assert sdk.messages.calls[0]["messages"][0]["content"] == "salom"


def test_pictures_go_before_the_prompt_each_after_its_label() -> None:
    client, sdk = asked(_Answer(GOOD))

    client.structured(
        prompt="qaysi kadr yaxshi?",
        schema=Draft,
        images=[Image(data=b"\xff\xd8one", label="Kadr 1"), Image(data=b"two")],
    )

    blocks = sdk.messages.calls[0]["messages"][0]["content"]
    assert [block["type"] for block in blocks] == ["text", "image", "image", "text"]
    assert blocks[0]["text"] == "Kadr 1"
    assert blocks[1]["source"] == {
        "type": "base64",
        "media_type": "image/jpeg",
        "data": base64.b64encode(b"\xff\xd8one").decode("ascii"),
    }
    assert blocks[-1]["text"] == "qaysi kadr yaxshi?"


def test_a_cut_off_answer_is_re_asked_with_the_pictures_still_there() -> None:
    client, sdk = asked(_Answer({}, stop_reason="max_tokens"), _Answer(GOOD))

    client.structured(prompt="salom", schema=Draft, images=[Image(data=b"x")])

    retry = sdk.messages.calls[1]["messages"][0]["content"]
    assert retry[0]["type"] == "image"
    assert retry[-1]["text"].startswith("salom")
