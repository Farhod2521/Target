"""The one chat's prompt: what is always sent, what a question brings, and
the faults ``chat_answer`` v28 had that this one must not repeat."""

import re
from pathlib import Path

import core.agent
from core.assistant.prompt import (
    BY_HEADING,
    BY_WORD,
    LANGUAGE_NAMES,
    VISITOR,
    language_name,
    sections_for,
    split,
)
from core.assistant.tools import TOOL_NAMES
from core.chat.context import ChatContext  # noqa: F401 - the headings' source

FOLDER = Path(core.agent.__file__).parent / "prompts" / "assistant"
VERSION = re.compile(r"^v(\d+)$")


def _latest() -> str:
    newest = max(
        (path for path in FOLDER.glob("v*.md") if VERSION.match(path.stem)),
        key=lambda path: int(VERSION.match(path.stem).group(1)),  # type: ignore[union-attr]
    )
    return newest.read_text(encoding="utf-8")


def test_the_base_is_short_and_every_section_is_marked() -> None:
    prompt = split(_latest())

    assert len(prompt.base.splitlines()) < 300
    assert set(prompt.sections) == {*BY_HEADING, *BY_WORD, VISITOR}
    assert "<!--" not in prompt.base
    for text in prompt.sections.values():
        assert text.startswith("## ")


def test_every_tool_the_model_is_given_is_named_in_the_prompt() -> None:
    """v28 named eight of fifteen and left the model to guess the rest."""
    base = split(_latest()).base

    missing = [name for name in TOOL_NAMES if f"`{name}`" not in base]
    assert missing == []


def test_every_section_the_context_can_carry_is_named_in_the_prompt() -> None:
    source = (
        Path(core.agent.__file__).parent.parent / "chat" / "context.py"
    ).read_text(encoding="utf-8")
    headings = {
        re.sub(r"\{[^}]*\}", "N", heading).replace("Last N days", "Last N days")
        for heading in re.findall(r'"#{2,3} ([^":]+)', source)
    }
    base = split(_latest()).base

    missing = [
        heading
        for heading in headings
        if heading.replace("The N days", "The N days") not in base
    ]
    assert missing == []


def test_the_language_is_told_as_a_name_never_a_code() -> None:
    assert language_name("uz") == LANGUAGE_NAMES["uz"]
    assert language_name("ru") == "Russian"
    assert language_name("xx") == LANGUAGE_NAMES["uz"]
    assert "{{ language }}" in _latest()


def test_no_support_marker_line_reaching_a_person_is_a_button() -> None:
    text = _latest()

    assert "%%SUPPORT%%" not in text
    assert "`create_ticket`" in text
    assert "Never say it was sent" in text


def test_house_rules_carried_over_from_chat_answer() -> None:
    base = split(_latest()).base

    for rule in (
        "Money is copied, not retyped",
        "A name goes in «these brackets»",
        "our word for the platform, not its name",
        "never the label itself",
        "Never write a number about this account",
    ):
        assert rule in base, rule


def test_a_question_brings_only_the_sections_it_needs() -> None:
    plain = sections_for(context="## Business\n- Name: X", question="Salom")
    assert plain == ()

    groups = sections_for(context="## Ad groups\n- a", question="nega qimmat")
    assert groups == ("groups",)

    video = sections_for(context="", question="Reels uchun ssenariy yozib ber")
    assert video == ("video",)

    later = sections_for(context="", question="ha", said=("video kerak",))
    assert later == ("video",)

    assert sections_for(context="## Ad groups", question="x", visitor=True) == (
        VISITOR,
    )


def test_the_tail_carries_the_sections_then_the_context() -> None:
    prompt = split(_latest())

    tail = prompt.tail(("groups",), context="## Business\n- Name: X")
    assert tail.index("## Why a group is not working") < tail.index("## Context")
    assert tail.endswith("- Name: X")
    assert "(empty)" in prompt.tail((), context="")
