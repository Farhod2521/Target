"""Rules every prompt a customer reads has to keep carrying.

No database, no Django and no model: the prompt files are read off disk and
asked whether the rule is still in them. That is a weaker test than it
looks like it should be, and it is the only one available - what these
rules are really checked by is a run against the real model, which costs
money and cannot be part of a suite. Both of these came out of such a run:
they were in nobody's test and in every answer.
"""

import re
from pathlib import Path

import core.agent
from core.chat.markdown import render
from core.chat.telegram import render_messages

PROMPTS = Path(core.agent.__file__).parent / "prompts"
VERSION = re.compile(r"^v(\d+)$")

# The two prompts whose answers a customer reads as prose. The section
# prompts fill fields on a screen and the night's one writes a note under a
# card, and neither quotes money back.
SURFACES = ("chat_answer", "weekly_report")


def latest(name: str) -> str:
    """The newest version of one prompt, compared as a number."""
    folder = PROMPTS / name
    newest = max(
        (path for path in folder.glob("v*.md") if VERSION.match(path.stem)),
        key=lambda path: int(str(VERSION.match(path.stem).group(1))),  # type: ignore[union-attr]
    )
    return newest.read_text(encoding="utf-8")


def test_every_answer_a_person_reads_copies_money_as_it_is_written() -> None:
    """A figure's spelling is part of the figure.

    The gate above these prompts checks the amount and nothing else, so
    "45 dollar" for "45 USD" passes every check there is and still leaves
    the reader with two shapes for one sum - one in the sentence and the
    other in the screen it sits under.
    """
    for name in SURFACES:
        assert "Money is copied, not retyped" in latest(name), name


def test_the_assistant_never_quotes_the_providers_own_words_for_a_rating() -> None:
    """It explained the rating in Uzbek and then put the English label in
    brackets beside it, which is the jargon rule undone by politeness."""
    text = latest("chat_answer")

    assert "never the label itself" in text
    # The fragment, not the sentence: the file is wrapped, and a phrase
    # that spans two lines is a phrase this test never finds.
    assert "in quotation marks, not in brackets" in text


def test_the_assistant_names_the_platform_the_way_the_screens_do() -> None:
    """The context calls it "provider" so that the domain code never names
    one, which is what keeps a second platform an adapter rather than a
    rewrite. The reader has only ever seen "Meta", and read the label as a
    name - in Uzbek it reads as an internet provider."""
    text = latest("chat_answer")

    assert "our word for the platform, not its name" in text


def test_the_assistant_writes_a_name_the_way_the_screens_write_one() -> None:
    """One product, one way of naming a campaign.

    The cabinet, the morning message and the weekly one all write «this».
    An answer that wrote "this" beside them read as coming from somewhere
    else - and put a campaign's name in the same marks as the name of a
    screen, which left the reader sorting out which of the two was theirs.
    """
    text = latest("chat_answer")

    assert "A name goes in «these brackets»" in text
    assert "A screen is named bare" in text
    assert "**No table**" in text


def test_the_shape_the_prompt_asks_for_is_the_shape_that_renders() -> None:
    """The prompt's example and the renderers' rule are one thing.

    This is the join that cannot be checked by reading either side. The
    model is asked for a shape and the renderers draw whatever matches
    their own pattern; a comma moved in one of the three would leave the
    prompt asking for rows nobody draws - and it would look correct in
    every file. So the example is read out of the prompt and put through
    both renderers.
    """
    lines = [
        line
        for line in latest("chat_answer").splitlines()
        if line.startswith("«") and " — " in line
    ]

    assert len(lines) >= 2, lines
    for line in lines:
        assert "<dl>" in render(line), line
        assert render_messages(line)[0].startswith("<b>«"), line


def test_every_answer_a_person_reads_names_a_campaign_one_way() -> None:
    """One message, one spelling of one name.

    The lines a report is built from write «this», and the sentence over
    them is the model's. A live run wrote the same campaign in quotation
    marks on one surface, lower-cased on another and shortened to one word
    on a third - three shapes for one campaign, in the same product, on the
    same morning.
    """
    for name in SURFACES:
        assert "«these brackets»" in latest(name), name
        assert "The long dash — separates" in latest(name), name


def test_the_assistant_writes_no_english_word_the_product_has_one_for() -> None:
    """The jargon list names what a media buyer says.

    It had nothing to say about the plain English word for a thing with an
    ordinary Uzbek one, and a live run wrote "reklama campaign" in a
    sentence to somebody who does not read English.
    """
    assert "Never an English word for something this product has a word for" in latest(
        "chat_answer"
    )
