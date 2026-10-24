"""Prompts as files, and the version that gets written down beside a call.

The rule these protect: a prompt is never edited in place. A new version
file is added beside the old one, and old ``LLMCall`` rows keep pointing at
what actually produced them. A result nobody can reproduce is a result
nobody can debug.
"""

from pathlib import Path

import pytest
from llmkit.errors import PromptNotFound
from llmkit.prompts import PromptLibrary, halves, missing_variables, render


@pytest.fixture
def library(tmp_path: Path) -> PromptLibrary:
    """Two prompts, one of them at ten versions."""
    audience = tmp_path / "audience"
    audience.mkdir()
    for number in range(1, 11):
        (audience / f"v{number}.md").write_text(f"draft {number}: {{{{ answers }}}}")

    form = tmp_path / "form_questions"
    form.mkdir()
    (form / "v1.md").write_text("questions")

    return PromptLibrary(root=tmp_path)


# --- Finding a prompt ----------------------------------------------------
def test_the_latest_version_is_compared_as_a_number(library: PromptLibrary) -> None:
    """As strings, v10 sorts before v9 - and the tenth version is where a
    product silently falls back to the ninth."""
    text, version = library.get("audience")

    assert version == "v10"
    assert text.startswith("draft 10")


def test_an_explicit_version_wins(library: PromptLibrary) -> None:
    """Pinning is how an old LLMCall row stays reproducible."""
    text, version = library.get("audience", version="v3")

    assert (version, text.startswith("draft 3")) == ("v3", True)


def test_the_version_used_is_returned_not_assumed(library: PromptLibrary) -> None:
    """It goes into a database column, and "latest" there means nothing."""
    _, version = library.get("form_questions")

    assert version == "v1"


def test_an_unknown_prompt_says_which_one(library: PromptLibrary) -> None:
    with pytest.raises(PromptNotFound) as caught:
        library.get("nonexistent")

    assert caught.value.name == "nonexistent"


def test_a_version_that_was_never_written_is_an_error(library: PromptLibrary) -> None:
    with pytest.raises(PromptNotFound):
        library.get("audience", version="v99")


def test_the_library_can_list_itself(library: PromptLibrary) -> None:
    assert library.names() == ("audience", "form_questions")


# --- Filling in variables ------------------------------------------------
def test_a_placeholder_is_replaced() -> None:
    assert render("Salom {{ name }}", {"name": "Aziz"}) == "Salom Aziz"


def test_spacing_inside_the_braces_does_not_matter() -> None:
    assert render("{{name}} va {{  name  }}", {"name": "x"}) == "x va x"


def test_json_braces_survive_untouched() -> None:
    """Prompts are full of JSON examples. Single braces must mean nothing."""
    template = 'Misol: {"age_min": 25}. Javob: {{ answers }}'

    assert render(template, {"answers": "[]"}) == 'Misol: {"age_min": 25}. Javob: []'


def test_a_variable_nobody_supplied_stays_visible() -> None:
    """Blanked, the prompt still reads as a sentence and produces a
    plausible wrong answer. Left visible, anybody spots it."""
    assert render("Javoblar: {{ answers }}", {}) == "Javoblar: {{ answers }}"


def test_the_missing_ones_can_be_listed_before_sending() -> None:
    template = "{{ answers }} va {{ business }} va {{ answers }}"

    assert missing_variables(template, {"business": "x"}) == ("answers",)


def test_nothing_missing_is_an_empty_tuple() -> None:
    assert missing_variables("{{ a }}", {"a": 1}) == ()


# --- The half a cache can hold --------------------------------------------
def test_a_prompt_splits_into_what_is_always_sent_and_what_is_not() -> None:
    """The mark is what makes a breakpoint worth placing: everything above
    it is identical from one account to the next, and a cache pays only for
    a prefix that repeats."""
    head, tail = halves(
        "Rules for everybody.\n\n<!-- account -->\n\n## The account\n\n{{ name }}"
    )

    assert head == "Rules for everybody."
    assert tail == "## The account\n\n{{ name }}"


def test_a_prompt_with_no_mark_claims_nothing_is_stable() -> None:
    """Which is every prompt written before the mark existed. The whole
    file comes back as the account half, so a caller that splits gets the
    call it made before - not a cached prefix that is different every
    time."""
    head, tail = halves("Everything here is about {{ name }}.")

    assert head == ""
    assert tail == "Everything here is about {{ name }}."
