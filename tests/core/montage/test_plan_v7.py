"""Prompt v7: every number in it comes from the code, and each of its three
examples, settled by the code as a real answer would be, keeps every
graphic it asks for."""

import json
import re
from typing import Any

import pytest
from llmkit import render
from llmkit.prompts import halves, missing_variables
from videokit import Brand

from core.agent import PROMPT_DIR as PROMPTS
from core.montage import SpokenWord
from core.montage.conflicts import clashes, conflicts_text
from core.montage.plan_v6 import plan_schema_v6
from core.montage.prompt_limits import limit_variables
from core.montage.rhythm import MAX_QUIET
from core.montage.settle import settle_v3

TEXT = (PROMPTS / "montage_plan" / "v7.md").read_text(encoding="utf-8")
BRAND = Brand(name="Namuna", cta_text="Telegram", cta_handle="@namuna")
_PHRASE = re.compile(r"^\[(\d+\.\d+)-(\d+\.\d+)\] \(#(\d+)-#(\d+)\) (.+)$")
# What the montage itself tells the planner, besides the shared limits.
_PER_MONTAGE = {
    "fillers", "catalogue", "target_seconds", "max_seconds", "aspect_ratio",
    "language", "style", "captions", "call_to_action", "brief", "brand_name",
    "brand_brief", "brand_contacts", "faces", "source_seconds", "transcript",
}  # fmt: skip


def _examples() -> list[tuple[list[str], list[dict[str, Any]]]]:
    """Each example: its transcript lines and its events."""
    blocks = re.findall(r"```\n(.*?)\n```\n\n```json\n(.*?)\n```", TEXT, re.S)
    return [(said.splitlines(), json.loads(events)) for said, events in blocks]


def _words(lines: list[str]) -> tuple[SpokenWord, ...]:
    """The words of an example, spread evenly over their phrase's seconds."""
    words: list[SpokenWord] = []
    for line in lines:
        start, end, first, last, text = _PHRASE.match(line).groups()  # type: ignore[union-attr]
        said = text.split()
        assert len(said) == int(last) - int(first) + 1, line
        step = (float(end) - float(start)) / len(said)
        for i, word in enumerate(said):
            at = float(start) + i * step
            words.append(
                SpokenWord(text=word, start=round(at, 3), end=round(at + step * 0.9, 3))
            )
        assert len(words) == int(last) + 1, line
    return tuple(words)


def test_there_are_three_examples() -> None:
    assert len(_examples()) == 3


@pytest.mark.parametrize("index", [0, 1, 2])
def test_each_example_is_a_valid_answer_and_keeps_every_graphic(index: int) -> None:
    lines, events = _examples()[index]
    words = _words(lines)
    # Everything after the first phrase (a greeting, or the hook itself:
    # cutting from the hook's first word keeps it).
    first = min(e["anchor_word"] for e in events)
    plan = plan_schema_v6(word_count=len(words)).model_validate(
        {
            "segments": [
                {"start": words[first].start, "end": words[-1].end, "role": "hook"}
            ],
            "events": events,
            "hook_type": "number",
            "content_matches_brand": True,
            "summary": "-",
        }
    )

    settled = settle_v3(
        plan=plan,
        source_seconds=words[-1].end + 5,
        target_seconds=60,
        words=words,
        brand=BRAND,
    )

    assert settled.dropped == ()
    shown = [c.name for c in settled.components]
    assert all(e["component"] in shown for e in events)


def test_the_example_ends_on_a_graphic_the_close_used_to_cover() -> None:
    lines, events = _examples()[0]
    words = _words(lines)
    plan = plan_schema_v6(word_count=len(words)).model_validate(
        {
            "segments": [
                {"start": words[1].start, "end": words[-1].end, "role": "hook"}
            ],
            "events": events,
            "hook_type": "number",
            "content_matches_brand": True,
            "summary": "-",
        }
    )

    settled = settle_v3(
        plan=plan, source_seconds=40, target_seconds=60, words=words, brand=BRAND
    )

    slams = [c for c in settled.components if c.name == "headline_slam"]
    card = next(c for c in settled.components if c.name == "end_card")
    assert slams[-1].start + slams[-1].length <= card.start + 1e-6
    assert card.start == pytest.approx(settled.length - settled.tail)


def test_every_variable_is_given_and_the_shared_ones_stay_in_the_cached_half() -> None:
    instructions, account = halves(TEXT)
    shared = limit_variables()

    assert not missing_variables(TEXT, shared | dict.fromkeys(_PER_MONTAGE, "x"))
    # The instructions are the same for every montage: only shared limits
    # and the catalogue and fillers, which are the same for all.
    assert set(re.findall(r"\{\{ (\w+) \}\}", instructions)) <= set(shared) | {
        "catalogue",
        "fillers",
    }
    assert "{{ transcript }}" in account and "{{ target_seconds }}" in account


def test_no_number_is_written_into_the_instructions_by_hand() -> None:
    """Outside the examples (transcripts and answers are data) and inline
    code (a transcript line's shape), every number is a variable."""
    head, rest = TEXT.split("## Examples", 1)
    prose = head + rest.split("## Before you answer", 1)[1]
    prose = re.sub(r"`[^`]*`", "", prose)
    prose = re.sub(r"^\d+\. ", "", prose, flags=re.M)

    assert not re.findall(r"\d", prose)


def test_the_limits_read_as_the_code_holds_them() -> None:
    told = render(halves(TEXT)[0], limit_variables() | {"catalogue": "", "fillers": ""})

    assert f"at least every {MAX_QUIET:g} seconds" in told
    assert "every two to four" not in told and "{{" not in told


def test_a_panel_and_a_headline_are_said_never_to_share_the_screen() -> None:
    found = clashes()

    assert "headline_slam" in found["checklist"]
    assert "checklist" in found["headline_slam"]
    # A sticker is a decoration: two of them never clash with each other.
    assert "sticker_fly" not in found["sticker_fly"]
    assert "cta_button" in found["lower_third"]
    assert "`headline_slam`" in conflicts_text()
