"""core/agent/schemas.py: what the model is allowed to write, and how much.

These bounds are a cost and a latency budget, not a formatting preference.
The schema is what the model reads while it fills a field in - a cap of six
hundred characters is read as an invitation to write six hundred - and every
character of the answer is billed and waited for by somebody watching a
progress bar.

The numbers are asserted rather than described because the pressure is
always upwards: one more field, one more sentence, each defensible on its
own and none of them visible on any screen.
"""

import pytest
from pydantic import ValidationError

from core.agent.schemas import (
    AudienceProposal,
    CreativeProposal,
    InterestProposal,
    InterestSection,
    LaunchDraft,
    LaunchDraftWithoutForm,
    TranslatedTerm,
    TranslatedTerms,
)
from core.targeting import MAX_AGE, MAX_RADIUS_KM, MIN_AGE, MIN_RADIUS_KM


def bounds_of(field: str) -> tuple[int | None, int | None]:
    """The numeric range on an ``AudienceProposal`` field."""
    caps = {
        type(item).__name__: item
        for item in AudienceProposal.model_fields[field].metadata
    }
    return (
        getattr(caps.get("Ge"), "ge", None),
        getattr(caps.get("Le"), "le", None),
    )


def bounds(model: type, field: str) -> tuple[int | None, int | None]:
    info = model.model_fields[field]
    caps = {type(item).__name__: item for item in info.metadata}
    low = getattr(caps.get("MinLen"), "min_length", None)
    high = getattr(caps.get("MaxLen"), "max_length", None)
    return low, high


# --- The list that dominates every answer --------------------------------
def test_the_interest_list_is_capped_at_a_screenful() -> None:
    """Two thirds of a draft is this list. Twenty interests is a list the
    owner scrolls past, which is a list they accept without reading."""
    assert bounds(LaunchDraft, "interests") == (6, 12)


def test_a_regenerated_list_is_capped_the_same_way() -> None:
    """Otherwise the cheap answer is the one nobody asked for twice."""
    assert bounds(InterestSection, "interests") == bounds(LaunchDraft, "interests")


def test_an_interest_reason_is_a_phrase_and_not_a_sentence() -> None:
    """It sits under a checkbox and is repeated once per interest, which
    made it the single largest thing the model writes."""
    _, high = bounds(InterestProposal, "reason")
    assert high is not None and high <= 70


# --- The bounds the platform sets ----------------------------------------
def an_audience(**overrides: object) -> dict[str, object]:
    return {
        "age_min": 25,
        "age_max": 45,
        "genders": [],
        "radius_km": 5,
        "reason": "Shahar markazidagi yoshlar",
        **overrides,
    }


def test_an_age_below_what_meta_delivers_to_is_pulled_up_not_refused() -> None:
    """One number out of range would otherwise cost the whole answer.

    The audience, the interests, three adverts and the form's questions
    are written in a single call; refusing all of them over an age Meta
    would not deliver to anyway buys another call, another half-minute,
    and no promise the next answer stays inside the bound either.
    """
    audience = AudienceProposal.model_validate(an_audience(age_min=16))

    assert audience.age_min == MIN_AGE
    assert audience.age_max == 45


def test_an_age_above_the_ceiling_comes_back_down_the_same_way() -> None:
    audience = AudienceProposal.model_validate(an_audience(age_max=70))

    assert audience.age_max == MAX_AGE


def test_an_age_in_range_is_left_exactly_as_proposed() -> None:
    """The clamp repairs one kind of answer. It must not quietly reshape
    the ones that were already right."""
    audience = AudienceProposal.model_validate(an_audience(age_min=21, age_max=54))

    assert (audience.age_min, audience.age_max) == (21, 54)


def test_an_age_that_is_not_a_number_is_still_a_refusal() -> None:
    """A malformed answer is not an out-of-range one, and pydantic's own
    message is better at saying so than a clamp would be."""
    with pytest.raises(ValidationError):
        AudienceProposal.model_validate(an_audience(age_min="o'n olti"))


def test_a_radius_wider_than_the_provider_allows_comes_down_too() -> None:
    """The same repair as the age, and leaving it out would have been the
    worse mistake: one model where a number eight years low is fixed and a
    number twenty kilometres wide is fatal. Both bounds are the
    provider's, and ``core.targeting`` clamps both further down."""
    audience = AudienceProposal.model_validate(an_audience(radius_km=200))

    assert audience.radius_km == MAX_RADIUS_KM
    assert AudienceProposal.model_validate(an_audience(radius_km=0)).radius_km == (
        MIN_RADIUS_KM
    )


def test_a_range_that_runs_downwards_is_refused_here_not_at_the_builder() -> None:
    """The one age problem with two readings, so the schema does not guess.

    At the builder it raises ``InvalidTargeting`` - and nothing in
    ``apps/`` catches that, so it lands in the guard that turns anything
    unlisted into "something went wrong". Raised here it is a re-ask with
    the reason attached.
    """
    with pytest.raises(ValidationError) as raised:
        AudienceProposal.model_validate(an_audience(age_min=45, age_max=25))

    assert "age_min 45 is above age_max 25" in str(raised.value)


def test_the_bounds_are_the_ones_the_targeting_layer_clamps_to() -> None:
    """Two copies of a provider limit is one copy that gets changed."""
    audience = AudienceProposal.model_validate(an_audience(age_min=1, age_max=99))

    assert (audience.age_min, audience.age_max) == (MIN_AGE, MAX_AGE)
    assert bounds_of("radius_km") == (MIN_RADIUS_KM, MAX_RADIUS_KM)


def test_a_gender_meta_does_not_have_is_refused_by_the_tool_itself() -> None:
    """An enum in the schema is checked on the provider's side, before a
    token of the answer is written - and the builder only ever filters this
    list on the edit path, so a stray code would go all the way to Meta."""
    with pytest.raises(ValidationError):
        AudienceProposal.model_validate(an_audience(genders=[3]))

    assert AudienceProposal.model_validate(an_audience(genders=[1])).genders == [1]


# --- Everything else -----------------------------------------------------
def test_the_ad_copy_stops_near_where_a_phone_stops_showing_it() -> None:
    """Meta hides everything past about 125 characters behind "See more"."""
    _, high = bounds(CreativeProposal, "primary_text")
    assert high is not None and high <= 300


def test_the_form_asks_for_the_fewest_questions_that_work() -> None:
    """Every extra question costs leads, which is the prompt's own rule -
    and the schema is what the model reads while answering."""
    assert bounds(LaunchDraft, "form_questions") == (2, 4)


def test_an_advert_with_no_form_is_asked_for_no_questions() -> None:
    """A chat, call, website or view advert shows nobody a question, and a
    list written for it would be billed and thrown away."""
    assert bounds(LaunchDraftWithoutForm, "form_questions") == (None, 0)


# --- The translation call ------------------------------------------------
def test_a_translated_term_carries_nothing_that_is_thrown_away() -> None:
    """It becomes a lookup key. A reason and a recommendation beside it
    would be written, billed and discarded unread on every one of them."""
    assert set(TranslatedTerm.model_fields) == {"label", "query"}


def test_translation_does_not_reuse_the_richer_interest_shape() -> None:
    field = TranslatedTerms.model_fields["terms"]
    assert field.annotation == list[TranslatedTerm]


def test_a_fifth_trait_is_dropped_rather_than_the_draft_refused() -> None:
    """Refusing it asked for the whole draft again - a second call."""
    names = ["a", "b", "c", "d", "e", "f"]

    assert LaunchDraft._first_traits(names) == ["a", "b", "c", "d"]
    assert bounds(LaunchDraft, "traits") == (None, 4)
