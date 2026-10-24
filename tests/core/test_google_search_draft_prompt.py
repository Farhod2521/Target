"""The Google Search prompt: one vocabulary with its schema, no blank left.

Held to the rule the Meta launch prompt is: every key of the answer named
in the prompt, in backticks, spelled as the schema spells it. And every
placeholder is one the preparation fills - a ``{{ name }}`` left in the
text is a sentence the model reads literally.
"""

import pytest
from llmkit import PromptLibrary, halves, missing_variables

from core.agent import PROMPT_DIR
from core.agent.schemas import GoogleSearchDraft

FILLED = {
    "goal_rule",
    "business_name",
    "business_category",
    "city",
    "country_code",
    "offer_text",
    "final_url",
    "places",
    "daily_budget",
}


def latest() -> str:
    text, _version = PromptLibrary(root=PROMPT_DIR).get("google_search_draft")
    return text


@pytest.mark.parametrize("name", sorted(GoogleSearchDraft.model_fields))
def test_every_key_of_the_answer_is_named_in_the_prompt(name: str) -> None:
    assert f"`{name}`" in latest()


def test_every_placeholder_is_one_the_preparation_fills() -> None:
    assert set(missing_variables(latest(), {})) == FILLED


def test_the_instructions_carry_no_account() -> None:
    """The stable half is the same for every campaign, so it can be cached."""
    instructions, _account = halves(latest())

    assert missing_variables(instructions, {}) == ()


def test_the_country_is_the_account_s_and_not_written_into_the_rules() -> None:
    """The market is the account's to say. The rules name Uzbekistan only as
    the example of what a country's searches look like."""
    instructions, account = halves(latest())

    assert "{{ country_code }}" in account
    assert "businesses in Uzbekistan" not in instructions
