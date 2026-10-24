"""The launch prompt and the schema it is answered in, held to one vocabulary.

The model reads both at once - the prompt while it plans the answer, the
schema while it writes it. A prompt that names none of the keys the answer
is made of, or calls an advert's two short fields "its own headline and its
own extra line", teaches words the schema does not demand: two vocabularies
for one answer. This holds them together: every key the answer is made of
is named in the prompt, in backticks, spelled as the schema spells it.
"""

import pytest
from llmkit import PromptLibrary

from core.agent import PROMPT_DIR
from core.agent.schemas import (
    AudienceProposal,
    CreativeProposal,
    FormQuestion,
    InterestProposal,
    LaunchDraft,
)

SHAPES = (
    LaunchDraft,
    AudienceProposal,
    InterestProposal,
    CreativeProposal,
    FormQuestion,
)


def latest_launch_prompt() -> str:
    text, _version = PromptLibrary(root=PROMPT_DIR).get("launch_draft")
    return text


@pytest.mark.parametrize(
    "name", sorted({field for shape in SHAPES for field in shape.model_fields})
)
def test_every_key_of_the_answer_is_named_in_the_prompt(name: str) -> None:
    assert f"`{name}`" in latest_launch_prompt()


def test_the_model_is_told_what_the_answer_is_rather_than_its_history() -> None:
    """The class docstring is written for whoever edits the file - sections
    withdrawn and brought back - and is not the description of the object
    the model is filling in."""
    description = LaunchDraft.model_json_schema()["description"]

    assert "withdrawn" not in description
    assert "audience" in description
