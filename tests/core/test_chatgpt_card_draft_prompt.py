"""The ChatGPT card prompt: one vocabulary with its schema, no blank left."""

import pytest
from llmkit import PromptLibrary, halves, missing_variables

from core.agent import PROMPT_DIR
from core.agent.schemas import ChatGPTCardDraft

FILLED = {
    "business_name",
    "business_category",
    "city",
    "country_code",
    "offer_text",
    "target_url",
}


def latest() -> str:
    text, _version = PromptLibrary(root=PROMPT_DIR).get("chatgpt_card_draft")
    return text


@pytest.mark.parametrize("name", sorted(ChatGPTCardDraft.model_fields))
def test_every_key_of_the_answer_is_named_in_the_prompt(name: str) -> None:
    assert f"`{name}`" in latest()


def test_every_placeholder_is_one_the_draft_fills() -> None:
    assert set(missing_variables(latest(), {})) == FILLED


def test_the_instructions_carry_no_account() -> None:
    instructions, _account = halves(latest())

    assert missing_variables(instructions, {}) == ()
