"""The advertiser's own audiences, on the two sides a spec keeps apart.

Everything in the provider guides that mattered has been read, and four of
these pin a place a guess would have been wrong:

* the two sides are **separate fields**, and the older shape - custom
  audiences nested inside ``exclusions`` - is deprecated
* an inclusion and an exclusion **combine**, and the provider's own example
  is a spec holding both
* an exclusion is a **non-negotiable constraint** that automation does not
  expand, while an inclusion is something the system delivers beyond
* a lookalike is listed as **removed** for a Special Ad Category, and the
  provider does not refuse it - it runs the campaign at ``WITH_ISSUES``

The fifth is not about the provider. An audience the provider will not
deliver on is **refused rather than dropped**, because an ad set built to
reach a named list of people and sent without that list reaches everybody
else instead - a wider audience than anyone approved, that looks from every
screen like it worked.

No Django, no network, no provider.
"""

import dataclasses

import pytest

from core.targeting import (
    EXCLUDE_KEY,
    INCLUDE_KEY,
    MAX_PER_SIDE,
    AudienceChoice,
    AudienceRef,
    AudienceUnusable,
    BusinessProfile,
    LookalikeNotAllowed,
    OnboardingAnswers,
    PresetCatalog,
    build,
    validate_launchable,
    validate_structure,
)
from core.targeting.contracts import BuiltTargeting
from core.targeting.exceptions import NoInterestsChosen

PROVIDER = "meta"

BASE = {"age_min": 25, "age_max": 45, "genders": [1]}


def _validated(spec: dict, **kwargs: object) -> tuple[dict, tuple]:
    """``validate_structure`` with the audience mode pinned.

    Every case in this file is about custom audiences, and none is about
    the automation switch - but the default is ``automatic``, which
    removes ``age_max`` and reports the removal. Left to the default, half
    the assertions here would be reading that adjustment instead of the one
    they were written for.
    """
    kwargs.setdefault("targeting_mode", "interests")
    return validate_structure(spec, **kwargs)  # type: ignore[arg-type]


BUYERS = AudienceRef(external_id="10", label="Mijozlar")
VISITORS = AudienceRef(external_id="20", label="Tashrif buyurganlar")
SIMILAR = AudienceRef(external_id="30", label="O'xshashlar", is_lookalike=True)
COUNTING = AudienceRef(external_id="40", label="Yangi ro'yxat", is_usable=False)


def _built(**overrides: object) -> BuiltTargeting:
    fields: dict[str, object] = {
        "objective": "OUTCOME_LEADS",
        "optimization_goal": "LEAD_GENERATION",
        "billing_event": "IMPRESSIONS",
        "destination_type": "ON_AD",
        "sends_to": "form",
        "call_to_action": "SIGN_UP",
        "targeting": {"age_min": 25, "flexible_spec": [{"interests": [{"id": "1"}]}]},
        # Pinned. The interest gate below only exists in this mode, and it
        # is not the default - a fixture taking the default would leave
        # every "still refused" test asserting nothing at all.
        "targeting_mode": "interests",
        "daily_budget_minor": 1000,
        "currency": "USD",
        "special_ad_categories": (),
        "preset_key": "restaurant/leads",
        "preset_version": "1",
    }
    return BuiltTargeting(**{**fields, **overrides})  # type: ignore[arg-type]


# --- The shape that goes out ----------------------------------------------
def test_each_side_is_a_list_of_objects_under_its_own_key() -> None:
    """Two fields, not one signed list. Custom audiences inside
    ``exclusions`` is the deprecated spelling and this is the current one."""
    spec, _notes = _validated(
        BASE, audiences=AudienceChoice(included=(BUYERS,), excluded=(VISITORS,))
    )

    assert spec[INCLUDE_KEY] == [{"id": "10"}]
    assert spec[EXCLUDE_KEY] == [{"id": "20"}]


def test_showing_and_excluding_happen_in_one_spec() -> None:
    """*"lookalike'ga ko'rsat, lekin mavjud mijozlarni chiqar"* is the most
    ordinary thing anybody does with these, and the provider documents it
    with an example holding both keys."""
    spec, _notes = _validated(
        BASE, audiences=AudienceChoice(included=(SIMILAR,), excluded=(BUYERS,))
    )

    assert spec[INCLUDE_KEY] and spec[EXCLUDE_KEY]


def test_a_side_nobody_used_is_absent_rather_than_empty() -> None:
    """An empty list is an error on some provider fields and a no-op on
    others, which is the worst of both. The sweep would remove it anyway;
    this never writes it."""
    spec, _notes = _validated(BASE, audiences=AudienceChoice(excluded=(BUYERS,)))

    assert INCLUDE_KEY not in spec
    assert EXCLUDE_KEY in spec


def test_a_launch_that_chose_nothing_names_neither_key() -> None:
    """Which is every campaign built before this question existed."""
    spec, _notes = _validated(BASE)

    assert INCLUDE_KEY not in spec
    assert EXCLUDE_KEY not in spec


def test_the_same_audience_twice_on_one_side_is_one_audience() -> None:
    """Silently, and with no adjustment: nothing was decided differently
    and nobody picked it twice on purpose."""
    spec, notes = _validated(BASE, audiences=AudienceChoice(included=(BUYERS, BUYERS)))

    assert spec[INCLUDE_KEY] == [{"id": "10"}]
    assert notes == ()


def test_the_documented_ceiling_is_five_hundred_a_side() -> None:
    """Far above anything a picker of somebody's own audiences produces.
    Written down rather than looked up again."""
    many = tuple(AudienceRef(external_id=str(n)) for n in range(MAX_PER_SIDE + 5))
    spec, _notes = _validated(BASE, audiences=AudienceChoice(included=many))

    assert len(spec[INCLUDE_KEY]) == MAX_PER_SIDE


# --- Both sides at once ---------------------------------------------------
def test_an_audience_on_both_sides_keeps_its_exclusion() -> None:
    """The picker cannot produce this - one radio group holds one value -
    so it arrives from a hand-edited form or an older draft. The direction
    is the safe one: the exclusion is what the provider treats as
    non-negotiable, and dropping it would widen an audience somebody
    deliberately narrowed."""
    spec, notes = _validated(
        BASE, audiences=AudienceChoice(included=(BUYERS,), excluded=(BUYERS,))
    )

    assert INCLUDE_KEY not in spec
    assert spec[EXCLUDE_KEY] == [{"id": "10"}]
    assert [n.reason for n in notes] == ["audience_on_both_sides"]


def test_the_contradiction_is_named_rather_than_counted() -> None:
    """A sentence saying "one of your audiences" is a sentence nobody can
    act on."""
    _spec, notes = _validated(
        BASE, audiences=AudienceChoice(included=(BUYERS,), excluded=(BUYERS,))
    )

    assert notes[0].detail == "Mijozlar"


# --- An audience that is no longer there ----------------------------------
def test_a_deleted_audience_is_reported_by_name() -> None:
    """There is no id left to send, so it cannot be carried - and saying
    nothing about it would leave somebody believing their campaign is aimed
    at a list it has never heard of."""
    _spec, notes = _validated(
        BASE, audiences=AudienceChoice(dropped=("Eski mijozlar",))
    )

    assert [(n.reason, n.detail) for n in notes] == [
        ("audience_unavailable", "Eski mijozlar")
    ]


# --- The gate: waiting rather than widening -------------------------------
@pytest.mark.parametrize("side", ["included", "excluded"])
def test_an_audience_the_provider_will_not_deliver_on_stops_the_launch(
    side: str,
) -> None:
    """**Both sides, and the second is the one worth stating.** An
    exclusion the provider refuses is not harmless: it is a list of people
    the advertiser believes are being kept away from the ad and who are
    not."""
    with pytest.raises(AudienceUnusable) as refused:
        validate_launchable(
            _built(audiences=AudienceChoice(**{side: (COUNTING,)}))  # type: ignore[arg-type]
        )

    assert refused.value.labels == ("Yangi ro'yxat",)


def test_it_is_refused_rather_than_quietly_left_out_of_the_spec() -> None:
    """The whole of the rule. Removing it would produce a legal spec that
    reaches everybody the rest of it allows - wider than anyone approved,
    paid for, and indistinguishable from success on every screen."""
    spec, _notes = _validated(BASE, audiences=AudienceChoice(included=(COUNTING,)))

    assert spec[INCLUDE_KEY] == [{"id": "40"}]


def test_a_usable_audience_passes_the_gate() -> None:
    validate_launchable(_built(audiences=AudienceChoice(included=(BUYERS,))))


# --- The gate: a named list is a targeted audience ------------------------
def test_an_included_audience_satisfies_the_interest_rule() -> None:
    """**The extension of the accident-against-choice rule, in the one
    direction that is safe.** The mode is carried because *absence* of
    detailed targeting is ambiguous - a choice or a failed lookup. Presence
    of a custom audience is not: an interest lookup that finds nothing
    cannot leave one behind, so a spec holding one was aimed by somebody."""
    validate_launchable(
        _built(
            targeting={"age_min": 25},
            audiences=AudienceChoice(included=(BUYERS,)),
        )
    )


def test_an_excluded_audience_does_not_satisfy_it() -> None:
    """Excluding people says who not to reach. It says nothing at all about
    who to reach, so the spec still targets nobody in particular."""
    with pytest.raises(NoInterestsChosen):
        validate_launchable(
            _built(
                targeting={"age_min": 25},
                audiences=AudienceChoice(excluded=(BUYERS,)),
            )
        )


def test_an_interest_launch_with_neither_is_still_refused() -> None:
    """The rule custom audiences are most likely to loosen by accident."""
    with pytest.raises(NoInterestsChosen):
        validate_launchable(_built(targeting={"age_min": 25}))


# --- A Special Ad Category removes one kind and keeps the other -----------
@pytest.mark.parametrize("side", ["included", "excluded"])
def test_a_lookalike_is_refused_beside_a_special_category(side: str) -> None:
    """*"Lookalike Audiences"* is listed as **removed** there, and the
    provider does not say so by refusing: it creates the ad set, marks the
    campaign with an issue and delivers nothing. Both sides, because the
    feature is withdrawn rather than one direction of it."""
    with pytest.raises(LookalikeNotAllowed) as refused:
        validate_launchable(
            _built(
                special_ad_categories=("HOUSING",),
                audiences=AudienceChoice(**{side: (SIMILAR,)}),  # type: ignore[arg-type]
            )
        )

    assert refused.value.labels == ("O'xshashlar",)


def test_an_ordinary_audience_is_allowed_beside_a_special_category() -> None:
    """*"Custom Audience Inclusion"* and *"Custom Audience Exclusion"* are
    both listed as supporting features there. Withholding them would be
    this product being stricter than the law it is enforcing."""
    validate_launchable(
        _built(
            special_ad_categories=("HOUSING",),
            audiences=AudienceChoice(included=(BUYERS,), excluded=(VISITORS,)),
        )
    )


def test_the_category_rule_is_checked_before_the_waiting_rule() -> None:
    """A lookalike beside a category is also unusable - the picker blocks
    it - and being told to wait for something that will never be allowed is
    worse than being told nothing."""
    barred = dataclasses.replace(SIMILAR, is_usable=False)

    with pytest.raises(LookalikeNotAllowed):
        validate_launchable(
            _built(
                special_ad_categories=("HOUSING",),
                audiences=AudienceChoice(included=(barred,)),
            )
        )


def test_the_category_still_removes_what_it_always_removed() -> None:
    """``excluded_custom_audiences`` is not the ``exclusions`` block. The
    first survives a category and the second does not, and a rule written
    against the wrong key would have taken the wrong one away."""
    spec, _notes = _validated(
        {**BASE, "exclusions": {"interests": [{"id": "9"}]}},
        special_ad_category="HOUSING",
        audiences=AudienceChoice(excluded=(BUYERS,)),
    )

    assert "exclusions" not in spec
    assert spec[EXCLUDE_KEY] == [{"id": "10"}]


# --- Through the builder --------------------------------------------------
def test_a_build_carries_the_choice_as_well_as_the_spec(
    catalog: PresetCatalog, answers: OnboardingAnswers, business: BusinessProfile
) -> None:
    """Carried rather than derived, for the reason ``targeting_mode`` is:
    the spec holds ids, and whether one of them is a lookalike or what to
    call it on a screen cannot be read back out of a number."""
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=business,
        catalog=catalog,
        currency="USD",
        audiences=AudienceChoice(included=(BUYERS,)),
    )

    assert built.targeting[INCLUDE_KEY] == [{"id": "10"}]
    assert built.audiences.included == (BUYERS,)


def test_a_build_that_was_given_nothing_carries_an_empty_choice(
    catalog: PresetCatalog, answers: OnboardingAnswers, business: BusinessProfile
) -> None:
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert built.audiences.is_empty
    assert INCLUDE_KEY not in built.targeting


@pytest.mark.parametrize("mode", ["interests", "broad", "automatic"])
def test_the_spec_is_the_same_whichever_mode_chose_it(
    mode: str,
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """**Nothing here branches on the mode**, and that is deliberate: the
    two sides are written identically in all three. What changes is the
    promise the screen makes about the included one, and a promise is not a
    field."""
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, targeting_mode=mode),  # type: ignore[arg-type]
        business=business,
        catalog=catalog,
        currency="USD",
        audiences=AudienceChoice(included=(BUYERS,), excluded=(VISITORS,)),
    )

    assert built.targeting[INCLUDE_KEY] == [{"id": "10"}]
    assert built.targeting[EXCLUDE_KEY] == [{"id": "20"}]
