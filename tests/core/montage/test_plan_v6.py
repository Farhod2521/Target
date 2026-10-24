"""Prompt v6's answer: one schema for every montage, bounds checked on the
answer, the hook's kind and the brand check kept for staff."""

import json

import pytest
from pydantic import ValidationError

from core.agent import PROMPT_DIR as PROMPTS
from core.montage.brief import faces_for_prompt
from core.montage.plan_v6 import MAX_EVENTS_V6, plan_facts, plan_schema_v6

ANSWER = {
    "segments": [{"start": 0.0, "end": 4.0, "role": "hook"},
                 {"start": 4.0, "end": 9.0, "role": "body", "transition_in": "burst"}],
    "events": [
        {"component": "hook_counter", "anchor_word": 0, "until_word": 5,
         "props": [{"name": "value", "text": "50%"},
                   {"name": "pill", "text": "chegirma"}],
         "beats": [{"name": "land", "words": [2]}]},
        {"component": "checklist", "anchor_word": 8, "until_word": 14,
         "props": [{"name": "title", "text": "Nega biz"},
                   {"name": "items", "items": ["Tez", "Arzon"]}],
         "beats": [{"name": "items", "words": [9, 12]}]},
    ],
    "emphasis": [3],
    "hook_type": "number",
    "content_matches_brand": True,
    "summary": "Chegirma va afzalliklar.",
}  # fmt: skip


def test_the_schema_is_the_same_whatever_the_transcript() -> None:
    """A schema that changed with the words would never be served from cache."""
    short = plan_schema_v6(word_count=20).model_json_schema()
    long = plan_schema_v6(word_count=900).model_json_schema()

    assert json.dumps(short, sort_keys=True) == json.dumps(long, sort_keys=True)
    assert short["properties"]["events"]["maxItems"] == MAX_EVENTS_V6


def test_word_numbers_past_the_transcript_are_handed_back() -> None:
    plan = plan_schema_v6(word_count=20).model_validate(ANSWER)

    assert plan_facts(plan) == {
        "hook_type": "number",
        "content_matches_brand": True,
        "roles": ["hook", "body"],
        "components": ["hook_counter", "checklist"],
    }
    with pytest.raises(ValidationError, match="past the last word"):
        plan_schema_v6(word_count=13).model_validate(ANSWER)


def test_layout_and_why_are_gone_from_a_stretch() -> None:
    schema = plan_schema_v6(word_count=20)
    stretch = {"start": 0.0, "end": 4.0, "role": "hook", "layout": "split_top"}

    with pytest.raises(ValidationError):
        schema.model_validate({**ANSWER, "segments": [stretch]})


def test_the_face_is_told_in_words() -> None:
    face = [2.0, 540, 960, [0.3, 0.4, 0.6, 0.7], [0.35, 0.45, 0.55, 0.65], 0.9]

    said = faces_for_prompt([face, face], stills=5)

    assert said.startswith("Found on 2 of 5 stills.")
    assert "45% across and 55% down" in said
    assert faces_for_prompt([], stills=5) == "No face was found on the 5 stills."


def test_the_planner_sees_the_changes_and_a_still_every_few_seconds_without() -> None:
    from core.montage.brief import MAX_SHOWN, MIN_SHOWN, shown_moments

    quiet = shown_moments([], duration=40.0)
    busy = shown_moments([i * 1.6 for i in range(50)], duration=80.0)

    # One shot all through: a still every five seconds, not every two.
    assert quiet == [0.5, 2.5, 7.5, 12.5, 17.5, 22.5, 27.5, 32.5, 37.5]
    assert len(shown_moments([], duration=8.0)) == MIN_SHOWN
    assert len(busy) == MAX_SHOWN


def test_each_event_is_read_into_its_own_components_model() -> None:
    plan = plan_schema_v6(word_count=20).model_validate(ANSWER)

    counter, checklist = plan.events
    assert counter.props.value == "50%" and counter.beats.land == 2
    assert checklist.props.items == ["Tez", "Arzon"]
    assert checklist.beats.items == [9, 12]
    wrong = {**ANSWER, "events": [{**ANSWER["events"][0], "component": "nope"}]}
    with pytest.raises(ValidationError, match="no component"):
        plan_schema_v6(word_count=20).model_validate(wrong)


def test_the_schema_is_small_enough_for_the_api_to_compile() -> None:
    """One union of a model per component compiled to a grammar the API
    refused as too large; one event shape for all keeps it small."""
    size = len(json.dumps(plan_schema_v6(word_count=50).model_json_schema()))

    assert size < 8_000


def test_the_prompts_own_example_is_a_valid_answer() -> None:
    text = (PROMPTS / "montage_plan" / "v6.md").read_text(encoding="utf-8")
    example = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])

    plan = plan_schema_v6(word_count=81).model_validate({**ANSWER, "events": example})

    assert len(plan.events) == len(example)
