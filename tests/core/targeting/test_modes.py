"""The three audience modes, and the one distinction the gate rests on.

Everything in the provider guides that mattered has been checked, and three
of these pin a place a guess would have been wrong:

* the automation switch has to be **sent either way** - from v23.0 an
  omitted one is the provider's own choice, and its own choice is on
* ``age_max`` is not clamped in the automatic mode, it is **removed**: the
  provider refuses any value at all
* ``age_min`` is capped at 25 there, not at the ordinary 18-65 band

The fourth is not about the provider. An audience with no interests because
somebody chose none and one with no interests because none survived
confirmation produce the **identical spec**, and only the first may launch -
so the gate reads the mode and never the spec. That is the whole of what
keeps the guard doing its job with three modes to tell apart.

No Django, no network, no provider.
"""

import dataclasses

import pytest
from adskit import MinorUnits

from core.targeting import (
    DEFAULT_TARGETING_MODE,
    MODES,
    BusinessProfile,
    Interest,
    OnboardingAnswers,
    PresetCatalog,
    TargetingMode,
    build,
    requires_interests,
    resolve_mode,
    sent_ages,
    validate_launchable,
    validate_structure,
    wants_interests,
)
from core.targeting.contracts import BuiltTargeting
from core.targeting.exceptions import NoInterestsChosen
from core.targeting.modes import (
    AUTOMATION_FIELD,
    AUTOMATION_KEY,
    AUTOMATION_OFF,
    AUTOMATION_ON,
)

PROVIDER = "meta"

BASE = {
    "age_min": 25,
    "age_max": 45,
    "genders": [1],
    "publisher_platforms": ["facebook"],
}


def _switch(spec: dict[str, object]) -> int:
    block = spec[AUTOMATION_KEY]
    assert isinstance(block, dict)
    return int(block[AUTOMATION_FIELD])


def _built(**overrides: object) -> BuiltTargeting:
    fields: dict[str, object] = {
        "objective": "OUTCOME_LEADS",
        "optimization_goal": "LEAD_GENERATION",
        "billing_event": "IMPRESSIONS",
        "destination_type": "ON_AD",
        "sends_to": "form",
        "call_to_action": "SIGN_UP",
        "targeting": {"age_min": 25},
        "daily_budget_minor": 1000,
        "currency": "USD",
        "special_ad_categories": (),
        "preset_key": "restaurant/leads",
        "preset_version": "1",
    }
    return BuiltTargeting(**{**fields, **overrides})  # type: ignore[arg-type]


# --- What is offered ------------------------------------------------------
def test_three_modes_and_the_recommended_one_leads() -> None:
    """The order is the picker's, and it opens on the provider's own
    recommendation - the same order ``PLACEMENT_MODES`` takes."""
    assert MODES == ("automatic", "interests", "broad")


def test_the_default_hands_the_decision_to_the_provider() -> None:
    """And it is **not** the value that changes nothing.

    ``interests`` is not neutral either: it writes an explicit
    ``advantage_audience: 0`` onto every campaign built with it. A row with
    no answer stored reads as the recommended mode, which widens delivery
    rather than leaving it where it was.
    """
    assert (
        OnboardingAnswers(
            category="restaurant", goal="calls", daily_budget_minor=MinorUnits(500)
        ).targeting_mode
        == "automatic"
    )


@pytest.mark.parametrize(
    ("mode", "wanted", "required"),
    [
        ("interests", True, True),
        ("broad", False, False),
        ("automatic", False, False),
    ],
)
def test_only_the_interests_mode_sends_interests(
    mode: TargetingMode, wanted: bool, required: bool
) -> None:
    """``automatic`` sends none: the provider would still deliver to a
    suggested interest first, and this mode leaves the audience to it."""
    assert wants_interests(mode) is wanted
    assert requires_interests(mode) is required


# --- The switch -----------------------------------------------------------
@pytest.mark.parametrize(
    ("mode", "value"),
    [
        ("interests", AUTOMATION_OFF),
        ("broad", AUTOMATION_OFF),
        ("automatic", AUTOMATION_ON),
    ],
)
def test_the_switch_is_always_sent_whichever_mode_it_is(
    mode: TargetingMode, value: int
) -> None:
    """From v23.0 an omitted switch is not "off" - it is the provider
    choosing, and it chooses on. A spec built here says what it wants."""
    spec, _notes = validate_structure(BASE, targeting_mode=mode)

    assert _switch(spec) == value


def test_the_switch_is_an_integer_and_not_a_boolean() -> None:
    """A form post turns ``True`` into the string "True", which the
    provider reads as a word and refuses while naming the field."""
    spec, _notes = validate_structure(BASE, targeting_mode="automatic")
    block = spec[AUTOMATION_KEY]
    assert isinstance(block, dict)

    assert isinstance(block[AUTOMATION_FIELD], int)
    assert not isinstance(block[AUTOMATION_FIELD], bool)


def test_the_switch_survives_the_empty_field_sweep() -> None:
    """It is written last and the sweep that follows removes empties. A
    block that ever became ``{}`` would be silently dropped, and a dropped
    switch means the provider decides."""
    spec, _notes = validate_structure({}, targeting_mode="broad")

    assert AUTOMATION_KEY in spec


# --- Age, in the automatic mode -------------------------------------------
def test_the_upper_age_is_removed_rather_than_pinned_at_sixty_five() -> None:
    """*"advertisers cannot set ``age_max`` values"* - sending the value
    the provider fixes it at is still sending a value, and it is refused
    while naming the field."""
    spec, notes = validate_structure(BASE, targeting_mode="automatic")

    assert "age_max" not in spec
    assert any(
        n.field == "age_max" and n.reason == "automatic_targeting" for n in notes
    )


def test_the_lower_age_is_capped_at_twenty_five() -> None:
    """*"advertisers can pass ``age_min`` values ranging between 18 to 25
    only"*. Above it the ad set is refused outright, so the correction has
    to happen here rather than at the provider."""
    spec, notes = validate_structure(
        {**BASE, "age_min": 40}, targeting_mode="automatic"
    )

    assert spec["age_min"] == 25
    assert any(n.field == "age_min" and n.detail == "40->25" for n in notes)


def test_an_age_already_inside_the_band_is_left_alone_and_unremarked() -> None:
    """The same bargain every other correction makes: a number that did not
    change must not produce a sentence saying it did."""
    spec, notes = validate_structure(
        {**BASE, "age_min": 20}, targeting_mode="automatic"
    )

    assert spec["age_min"] == 20
    assert [n for n in notes if n.field == "age_min"] == []


@pytest.mark.parametrize("mode", ["interests", "broad"])
def test_the_other_two_modes_keep_the_age_the_owner_typed(
    mode: TargetingMode,
) -> None:
    spec, notes = validate_structure(BASE, targeting_mode=mode)

    assert spec["age_min"] == 25
    assert spec["age_max"] == 45
    assert [n for n in notes if n.reason == "automatic_targeting"] == []


# --- The gate: accident against choice ------------------------------------
def test_a_broad_audience_somebody_chose_may_launch_with_no_interests() -> None:
    validate_launchable(_built(targeting_mode="broad", targeting={"age_min": 25}))


def test_an_automatic_audience_may_launch_with_no_interests() -> None:
    validate_launchable(_built(targeting_mode="automatic", targeting={"age_min": 25}))


def test_an_interest_audience_whose_interests_all_failed_is_still_refused() -> None:
    """**The rule this whole stage was most likely to break.** The guard
    was written to catch a launch whose confirmed interests all vanished,
    and the day a broad mode existed it could have started reading that
    accident as a choice - because the two produce the same spec."""
    with pytest.raises(NoInterestsChosen):
        validate_launchable(_built(targeting_mode="interests"))


def test_the_two_are_indistinguishable_from_the_spec_alone() -> None:
    """Which is why the gate reads the mode. Pinned as its own test because
    the temptation is to check ``flexible_spec`` and be done."""
    accident = _built(targeting_mode="interests", targeting={"age_min": 25})
    choice = _built(targeting_mode="broad", targeting={"age_min": 25})

    assert accident.targeting == choice.targeting
    with pytest.raises(NoInterestsChosen):
        validate_launchable(accident)
    validate_launchable(choice)


# --- Through the builder --------------------------------------------------
def test_a_broad_build_sends_no_detailed_targeting_at_all(
    catalog: PresetCatalog, answers: OnboardingAnswers, business: BusinessProfile
) -> None:
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, targeting_mode="broad"),
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert "flexible_spec" not in built.targeting
    assert built.targeting_mode == "broad"
    assert _switch(dict(built.targeting)) == AUTOMATION_OFF


def test_an_automatic_build_sends_no_interests(
    catalog: PresetCatalog, answers: OnboardingAnswers, business: BusinessProfile
) -> None:
    """The provider still delivers to a suggested interest first, so one
    wrong suggestion steers the first spend. None go, and none is reported
    as dropped - nobody asked for them to be used."""
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(
            answers,
            targeting_mode="automatic",
            interests=(
                *answers.interests,
                Interest(label="Sartaroshxona", query="Barbershop"),
            ),
        ),
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert "flexible_spec" not in built.targeting
    assert _switch(dict(built.targeting)) == AUTOMATION_ON
    assert not [a for a in built.adjustments if a.reason == "unconfirmed_interest"]


def test_a_broad_build_does_not_report_interests_as_dropped(
    catalog: PresetCatalog, answers: OnboardingAnswers, business: BusinessProfile
) -> None:
    """They were not going to be used. Reporting them would be telling
    somebody their choice failed when they had chosen not to make it."""
    with_unconfirmed = dataclasses.replace(
        answers,
        targeting_mode="broad",
        interests=(Interest(label="Sartaroshxona", query="Barbershop"),),
    )
    built = build(
        provider=PROVIDER,
        answers=with_unconfirmed,
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert [n for n in built.adjustments if n.reason == "unconfirmed_interest"] == []


def test_every_preset_gets_the_switch_although_no_preset_carries_it(
    catalog: PresetCatalog, answers: OnboardingAnswers, business: BusinessProfile
) -> None:
    """It is an answer rather than a preset property. Two places deciding
    one field is one place that has to lose, silently.

    Both values are asserted through the builder rather than one, because
    what this pins is that the switch is *written* - the failure it guards
    is an absent key, which the provider reads as its own choice.
    """
    on = build(
        provider=PROVIDER,
        answers=answers,
        business=business,
        catalog=catalog,
        currency="USD",
    )
    off = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, targeting_mode="interests"),
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert _switch(dict(on.targeting)) == AUTOMATION_ON
    assert _switch(dict(off.targeting)) == AUTOMATION_OFF


def test_no_preset_file_still_names_the_provider_switch(
    catalog: PresetCatalog,
) -> None:
    """Locked, because leaving one behind would be invisible: the builder
    overwrites it, so the stale line would sit in the file looking
    authoritative and deciding nothing."""
    for preset in catalog._by_key.values():
        assert AUTOMATION_KEY not in preset.targeting


# --- A Special Ad Category overrules the answer ---------------------------
@pytest.mark.parametrize("mode", ["broad", "automatic"])
def test_a_special_category_forces_the_mode_back_and_says_so(
    mode: TargetingMode,
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """The provider documents nothing about whether the switch is even
    accepted beside a category, and ``0`` is what these campaigns have been
    sent since before any of this existed. Silence is read as the value
    that already works."""
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, targeting_mode=mode),
        business=dataclasses.replace(business, special_ad_category="HOUSING"),
        catalog=catalog,
        currency="USD",
    )

    assert built.targeting_mode == "interests"
    assert _switch(dict(built.targeting)) == AUTOMATION_OFF
    assert any(
        n.field == "targeting_automation" and n.reason == "special_ad_category"
        for n in built.adjustments
    )


def test_a_special_category_choosing_the_forced_mode_reports_nothing(
    catalog: PresetCatalog, answers: OnboardingAnswers, business: BusinessProfile
) -> None:
    """Nothing was overruled, so nothing is said. A note here would be
    describing a decision back to the person who made it.

    ``interests`` is passed explicitly. It is the mode the category forces
    and not the one an unanswered launch arrives with, so a category
    campaign that says nothing *is* overruled - and is told so by the test
    below this one.
    """
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, targeting_mode="interests"),
        business=dataclasses.replace(business, special_ad_category="HOUSING"),
        catalog=catalog,
        currency="USD",
    )

    assert [n for n in built.adjustments if n.field == "targeting_automation"] == []


def test_a_special_category_taking_the_default_is_overruled_and_told(
    catalog: PresetCatalog, answers: OnboardingAnswers, business: BusinessProfile
) -> None:
    """The case the default creates, and the reason the switch is forced.

    Meta's documentation says nothing about whether the automation switch
    is even accepted beside a Special Ad Category, and the honest reading
    of silence is the value that already works. So a housing, employment or
    credit campaign is built with the switch off whatever the default is -
    and that is a correction the advertiser is told about rather than a
    coincidence.
    """
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=dataclasses.replace(business, special_ad_category="HOUSING"),
        catalog=catalog,
        currency="USD",
    )

    assert built.targeting_mode == "interests"
    assert _switch(dict(built.targeting)) == AUTOMATION_OFF
    assert [
        n.reason for n in built.adjustments if n.field == "targeting_automation"
    ] == ["special_ad_category"]


# --- What a card says is being bought ------------------------------------
def test_automatic_targeting_sends_no_upper_age_and_caps_the_lower_one() -> None:
    assert sent_ages(30, 55, mode="automatic") == (25, None)
    assert sent_ages(20, 55, mode="automatic") == (20, None)


def test_the_other_modes_send_the_range_as_typed() -> None:
    assert sent_ages(30, 55, mode="interests") == (30, 55)
    assert sent_ages(30, 55, mode="broad") == (30, 55)


def test_a_missing_or_unknown_mode_reads_as_the_default() -> None:
    """The builder's own reading, so a card cannot describe another mode."""
    assert resolve_mode(None) == DEFAULT_TARGETING_MODE
    assert resolve_mode("nonsense") == DEFAULT_TARGETING_MODE
    assert resolve_mode("broad") == "broad"


def test_the_card_ages_match_the_spec_the_builder_sends(
    catalog: PresetCatalog, answers: OnboardingAnswers, business: BusinessProfile
) -> None:
    """One rule, two readers: what the card says and what goes out agree."""
    wanted = dataclasses.replace(
        answers, age_min=30, age_max=55, targeting_mode="automatic"
    )
    built = build(
        provider=PROVIDER,
        answers=wanted,
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert sent_ages(30, 55, mode="automatic") == (
        built.targeting.get("age_min"),
        built.targeting.get("age_max"),
    )
