"""Where the ad is shown: two states, one list, and a table of dead values.

The two states differ by **absence**, which is what most of this file is
about. A spec with no placement key is not an unfinished spec - it is the
provider being told to choose, and it is the provider's own default. So the
tests that matter are the ones that check nothing is there.
"""

import dataclasses

import pytest
from adskit import MinorUnits

from core.targeting import (
    PLACEMENT_MODES,
    RETIRED_POSITIONS,
    STANDARD_PLACEMENTS,
    BusinessProfile,
    OnboardingAnswers,
    PresetCatalog,
    build,
    validate_structure,
)
from core.targeting.placements import (
    DEFAULT_PLACEMENT_MODE,
    OFFERED_POSITIONS,
    PLACEMENT_KEYS,
    POSITION_NEEDS,
    fit,
    keep_chat_reachable,
    lonely_position,
    names_a_placement,
    strip_retired,
)

PROVIDER = "meta"

BASE: dict[str, object] = {
    "age_min": 25,
    "age_max": 45,
    "geo_locations": {"countries": ["UZ"]},
}


def _placements(spec: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in spec.items() if key in PLACEMENT_KEYS}


# --- The two states -------------------------------------------------------
#
# ``targeting_mode`` is pinned through this section. It is the other half
# of the same dialog and it defaults to ``automatic``, which files an
# ``age_max`` adjustment of its own - and every case here asserts that the
# placement decision reported nothing.


def test_the_standard_state_writes_the_list_this_product_has_always_bought() -> None:
    spec, notes = validate_structure(
        BASE, placement_mode="standard", targeting_mode="interests"
    )

    assert spec["publisher_platforms"] == ["facebook", "instagram"]
    assert spec["facebook_positions"] == ["feed"]
    assert spec["instagram_positions"] == ["stream", "story", "reels"]
    assert notes == ()


def test_the_automatic_state_sends_no_placement_key_at_all() -> None:
    """Absence *is* the instruction.

    "No action is required to opt in to Advantage+ placement, as it is the
    default setting in the API" - so one key left behind would opt the ad
    set back out, and the spec would quietly be a manual one again.
    """
    spec, notes = validate_structure(
        BASE, placement_mode="automatic", targeting_mode="interests"
    )

    assert _placements(spec) == {}
    assert notes == ()


def test_the_default_is_the_provider_recommendation_and_changes_things() -> None:
    """The default is the automatic state, and it is not a no-op.

    Unlike ``DEFAULT_TARGETING_MODE`` this default does not leave delivery
    where a standard list would put it - it widens it. Asserted through the
    validator and not only off the constant, because the constant means
    nothing if the block it is meant to suppress is still written.
    """
    assert DEFAULT_PLACEMENT_MODE == "automatic"

    spec, _ = validate_structure(BASE)

    assert not [key for key in PLACEMENT_KEYS if key in spec]


def test_the_recommended_state_leads_and_the_retired_one_comes_last() -> None:
    """The provider's choice first, one app each, and the retired pair
    last - kept only so launches approved with it still read."""
    assert PLACEMENT_MODES == ("automatic", "instagram", "facebook", "standard")


def test_instagram_alone_names_no_other_app() -> None:
    spec, _ = validate_structure(BASE, placement_mode="instagram")

    assert spec["publisher_platforms"] == ["instagram"]
    assert spec["instagram_positions"] == ["stream", "story", "reels"]
    assert "facebook_positions" not in spec


def test_facebook_alone_names_no_other_app() -> None:
    spec, _ = validate_structure(BASE, placement_mode="facebook")

    assert spec["publisher_platforms"] == ["facebook"]
    assert spec["facebook_positions"] == ["feed", "story", "facebook_reels"]
    assert "instagram_positions" not in spec


@pytest.mark.parametrize(
    ("mode", "chat", "kept"),
    [
        ("instagram", "instagram", True),
        ("facebook", "messenger", True),
        ("instagram", "messenger", False),
        ("facebook", "instagram", False),
    ],
)
def test_a_chat_in_the_other_app_hands_the_choice_back(
    mode: str, chat: str, kept: bool
) -> None:
    spec, notes = validate_structure(BASE, placement_mode=mode)  # type: ignore[arg-type]
    notes = list(notes)

    keep_chat_reachable(spec, notes, mode=mode, chat=chat)  # type: ignore[arg-type]

    assert ("publisher_platforms" in spec) is kept
    assert any(n.reason == "unsupported_placement" for n in notes) is not kept


# --- Replacement, in both directions --------------------------------------


def test_a_placement_a_stored_spec_carried_does_not_survive_either_state() -> None:
    """An absent key means delete, never leave as it was.

    The failure this ends: a stored spec naming ``messenger_positions`` in
    a list that no longer includes Messenger, with nothing overwriting it
    because nothing owns it.
    """
    stale = {
        **BASE,
        "publisher_platforms": ["facebook", "messenger"],
        "messenger_positions": ["messenger_home"],
        "audience_network_positions": ["classic"],
        "device_platforms": ["mobile"],
    }

    standard, _ = validate_structure(stale, placement_mode="standard")
    automatic, _ = validate_structure(stale, placement_mode="automatic")

    assert _placements(standard) == {
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["feed"],
        "instagram_positions": ["stream", "story", "reels"],
    }
    assert _placements(automatic) == {}


def test_every_key_the_provider_reads_a_placement_from_is_wiped() -> None:
    """Including the two v26.0 added. A key this file has never heard of is
    the one that gets left behind, so the list is exhaustive rather than
    limited to what the standard state writes."""
    spec = {key: ["something"] for key in PLACEMENT_KEYS}
    fit(spec, [], mode="automatic")

    assert spec == {}


# --- What the provider no longer accepts ----------------------------------


def test_the_standard_list_holds_nothing_the_provider_has_retired() -> None:
    """The two tables move on different clocks - ours when somebody decides,
    theirs when a changelog says so - and this is where they are compared."""
    for key, values in STANDARD_PLACEMENTS.items():
        retired = RETIRED_POSITIONS.get(key, ())
        assert not set(values) & set(retired), key


def test_instagram_explore_is_stripped_because_it_is_refused() -> None:
    """v26.0: "requests that explicitly specify Explore return an error".

    Both spellings, because the changelog names the placement and the
    reference page lists the pair.
    """
    spec: dict[str, object] = {"instagram_positions": ["stream", "explore"]}
    notes: list[object] = []

    strip_retired(spec, notes)  # type: ignore[arg-type]

    assert spec["instagram_positions"] == ["stream"]
    assert [n.reason for n in notes] == ["unsupported_placement"]  # type: ignore[attr-defined]


def test_the_messenger_story_is_stripped_and_that_one_would_have_been_silent() -> None:
    """ "The `story` value in `messenger_positions` is silently removed for
    versioned v26.0 or later calls." A refused value costs a launch and is
    found; a silently dropped one costs nothing and is never found, because
    the campaign runs and the screen still names the placement."""
    spec: dict[str, object] = {"messenger_positions": ["sponsored_messages", "story"]}
    notes: list[object] = []

    strip_retired(spec, notes)  # type: ignore[arg-type]

    assert spec["messenger_positions"] == ["sponsored_messages"]


def test_the_facebook_video_feed_is_not_treated_as_retired() -> None:
    """The evidence for retiring it is not there.

    The v26.0 reference lists ``video_feeds`` as live with no deprecation
    note anywhere, and stripping a placement the provider accepts is a
    screen reporting a change nobody made.
    """
    assert "facebook_positions" not in RETIRED_POSITIONS

    spec: dict[str, object] = {"facebook_positions": ["feed", "video_feeds"]}
    strip_retired(spec, [])

    assert spec["facebook_positions"] == ["feed", "video_feeds"]


# --- The two vocabularies -------------------------------------------------


def test_the_list_is_written_in_targeting_words_not_reporting_words() -> None:
    """An ad set targeted with ``instagram_positions: [stream]`` has its
    figures returned under ``instagram|feed``, and Audience Network is
    targeted as ``classic`` and reported as ``an_classic``. Nothing
    translates between them, so anything matching a breakdown row against
    this list needs a map - and finding that out from a rule that silently
    never matches is expensive."""
    assert "stream" in STANDARD_PLACEMENTS["instagram_positions"]
    assert "feed" not in STANDARD_PLACEMENTS["instagram_positions"]
    assert "feed" in STANDARD_PLACEMENTS["facebook_positions"]


# --- The catalogue does not get a say -------------------------------------


def test_no_preset_in_the_catalogue_names_a_placement(
    catalog: PresetCatalog,
) -> None:
    """Refused by the loader, and checked here against the real files.

    Where the tap lands and where the ad is shown are two questions, and
    twelve copies of the answer to the second are how a placement outlives
    its own removal.
    """
    for category in catalog.categories(provider=PROVIDER):
        for preset in catalog.goals(provider=PROVIDER, category=category.key):
            assert names_a_placement(preset.targeting) == (), preset.key


# --- End to end -----------------------------------------------------------


def test_the_answer_travels_to_the_built_spec(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """Carried rather than derived, and here the reason is sharper than it
    is for the audience mode: in the automatic state the spec holds no
    placement key, so reading it back could not tell "the provider chooses"
    from "nobody asked"."""
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, placement_mode="automatic"),
        business=business,
        catalog=catalog,
        currency="UZS",
    )

    assert built.placement_mode == "automatic"
    assert _placements(dict(built.targeting)) == {}


def test_a_launch_that_answers_nothing_gets_the_provider_recommendation(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """No answer means the recommended state, and the spec proves it.

    The pair of assertions is the point: the mode carried on the result and
    the keys actually written have to agree, or a screen reports one
    placement decision while the provider is sent another.
    """
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=business,
        catalog=catalog,
        currency="UZS",
    )

    assert built.placement_mode == "automatic"
    assert "publisher_platforms" not in built.targeting


def test_a_special_ad_category_takes_nothing_away_here(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """A decision, not an omission.

    The category overrules the audience mode because the provider is silent
    about whether the automation switch is accepted beside one. It is silent
    about placements too, and the two silences are not the same: that switch
    decides who the audience is, which is the thing the category exists to
    regulate, and this one does not. Narrowing delivery on a rule nobody
    wrote would be inventing a restriction.
    """
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, placement_mode="automatic"),
        business=dataclasses.replace(business, special_ad_category="HOUSING"),
        catalog=catalog,
        currency="UZS",
    )

    assert built.placement_mode == "automatic"
    assert _placements(dict(built.targeting)) == {}
    assert not [note for note in built.adjustments if note.field in PLACEMENT_KEYS]


@pytest.mark.parametrize("mode", PLACEMENT_MODES)
def test_every_state_produces_a_spec_the_budget_still_governs(
    mode: str,
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """Placement changes where money goes, never how much of it."""
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(
            answers,
            placement_mode=mode,  # type: ignore[arg-type]
            daily_budget_minor=MinorUnits(700),
        ),
        business=business,
        catalog=catalog,
        currency="UZS",
    )

    assert built.daily_budget_minor == 700


# --- The positions an owner ticked ----------------------------------------


def test_positions_replace_the_block_of_their_app() -> None:
    spec, _ = validate_structure(
        BASE,
        placement_mode="instagram",
        placement_positions={"instagram": ("story",)},
    )
    assert _placements(spec) == {
        "publisher_platforms": ["instagram"],
        "instagram_positions": ["story"],
    }


def test_positions_of_an_app_the_mode_skips_are_not_written() -> None:
    spec, _ = validate_structure(
        BASE,
        placement_mode="instagram",
        placement_positions={"facebook": ("feed",)},
    )
    assert "facebook_positions" not in spec
    assert spec["instagram_positions"] == ["stream", "story", "reels"]


def test_no_positions_leave_the_saved_launches_as_they_were() -> None:
    for mode in ("instagram", "facebook", "standard"):
        plain, _ = validate_structure(BASE, placement_mode=mode)  # type: ignore[arg-type]
        none, _ = validate_structure(
            BASE,
            placement_mode=mode,  # type: ignore[arg-type]
            placement_positions={},
        )
        assert plain == none


def test_automatic_ignores_positions() -> None:
    spec, _ = validate_structure(
        BASE,
        placement_mode="automatic",
        placement_positions={"instagram": ("story",)},
    )
    assert _placements(spec) == {}


def test_a_position_never_offered_is_not_written() -> None:
    spec, _ = validate_structure(
        BASE,
        placement_mode="instagram",
        placement_positions={"instagram": ("explore", "story")},
    )
    assert spec["instagram_positions"] == ["story"]


def test_every_needed_position_is_one_an_owner_can_tick() -> None:
    for (app, item), needs in POSITION_NEEDS.items():
        assert item in OFFERED_POSITIONS[app]
        for other, position in needs:
            assert position in OFFERED_POSITIONS[other]


@pytest.mark.parametrize(
    ("mode", "ticked", "lonely"),
    [
        ("facebook", {"facebook": ("story",)}, ("facebook", "story")),
        ("facebook", {"facebook": ("feed", "story")}, None),
        ("standard", {"facebook": ("story",), "instagram": ("story",)}, None),
        (
            "standard",
            {"facebook": ("story",), "instagram": ("stream",)},
            ("facebook", "story"),
        ),
        ("instagram", {"instagram": ("profile_feed",)}, ("instagram", "profile_feed")),
        ("instagram", {"instagram": ("story", "ig_search")}, None),
        ("automatic", {"facebook": ("story",)}, None),
    ],
)
def test_a_position_that_cannot_run_alone_is_found(
    mode: str, ticked: dict[str, tuple[str, ...]], lonely: tuple[str, str] | None
) -> None:
    assert lonely_position(ticked, mode=mode) == lonely


def test_the_default_blocks_break_no_rule() -> None:
    for mode in PLACEMENT_MODES:
        assert lonely_position(None, mode=mode) is None
