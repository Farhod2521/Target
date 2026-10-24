"""Answers plus a preset, in - a spec, out. The whole package in one call.

Nothing here needs a database, a network, a clock or a settings module.
That is the point of the layer: the wizard has to work end to end for
someone who has not connected an ad account yet, and these tests are what
prove it still does.
"""

import dataclasses

import pytest
from adskit import MinorUnits

from core.targeting import (
    BusinessProfile,
    Interest,
    OnboardingAnswers,
    PresetCatalog,
    build,
    fallback,
)
from core.targeting.exceptions import InvalidTargeting, UnfilledTemplate
from core.targeting.geo import GeoChoice

PROVIDER = "meta"

CONFIRMED = Interest(
    label="Restoranlar", query="Restaurants", external_id="6003", audience_size=900_000
)
UNCONFIRMED = Interest(label="Sartaroshxona", query="Barbershop")


def test_the_preset_decides_the_provider_knobs(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """Never the AI. A wrong optimisation goal spends on the wrong outcome."""
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert built.objective == "OUTCOME_TRAFFIC"
    assert built.optimization_goal == "QUALITY_CALL"
    assert built.billing_event == "IMPRESSIONS"
    assert built.destination_type == "PHONE_CALL"


def test_the_answers_decide_who_sees_it(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """The mode is pinned because the upper age is what this asserts.

    Under the default the provider fixes ``age_max`` at 65 and the builder
    removes the field rather than send one - which is that mode's own
    behaviour, tested in ``test_modes.py``, and not the answers deciding
    anything.
    """
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, targeting_mode="interests"),
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert built.targeting["age_min"] == 25
    assert built.targeting["age_max"] == 45
    assert built.targeting["genders"] == [1, 2]
    assert built.targeting["locales"] == [67, 26]


def test_the_business_pin_becomes_the_geography(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=business,
        catalog=catalog,
        currency="USD",
    )
    location = built.targeting["geo_locations"]["custom_locations"][0]

    assert location["latitude"] == "41.311081"
    assert location["radius"] == 5


def test_an_unanswered_question_falls_back_to_the_preset(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """Which is what makes a four-question wizard possible at all."""
    bare = dataclasses.replace(answers, radius_km=None, age_min=None, age_max=None)

    built = build(
        provider=PROVIDER,
        answers=bare,
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert built.targeting["geo_locations"]["custom_locations"][0]["radius"] == 5
    assert built.targeting["age_min"] == 20


def test_a_confirmed_interest_travels_with_both_its_id_and_its_name(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """The name is what a person can still check a year later."""
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(
            answers, interests=(CONFIRMED,), targeting_mode="interests"
        ),
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert built.targeting["flexible_spec"] == [
        {"interests": [{"id": "6003", "name": "Restaurants"}]}
    ]


def test_an_unconfirmed_interest_is_dropped_but_not_hidden(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """The owner picked it. A list that quietly shrinks reads as a bug."""
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(
            answers, interests=(CONFIRMED, UNCONFIRMED), targeting_mode="interests"
        ),
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert len(built.targeting["flexible_spec"][0]["interests"]) == 1
    assert [
        (a.reason, a.detail) for a in built.adjustments if a.field == "flexible_spec"
    ] == [("unconfirmed_interest", "Sartaroshxona")]


def test_no_confirmed_interest_leaves_the_spec_without_one(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """Building is not launching. Before a connection exists, nothing is
    confirmed, and refusing here would make the wizard unusable."""
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, interests=(UNCONFIRMED,)),
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert "flexible_spec" not in built.targeting


def test_a_special_ad_category_reaches_the_campaign_level(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    housing = dataclasses.replace(
        business, category="real_estate", special_ad_category="HOUSING"
    )

    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, category="real_estate", goal="leads"),
        business=housing,
        catalog=catalog,
        currency="USD",
    )

    assert built.special_ad_categories == ("HOUSING",)
    assert "flexible_spec" not in built.targeting
    assert "genders" not in built.targeting


@pytest.mark.parametrize(
    ("stored", "sent"),
    [
        ("housing", "HOUSING"),
        ("employment", "EMPLOYMENT"),
        # Meta refuses CREDIT since January 2025.
        ("credit", "FINANCIAL_PRODUCTS_SERVICES"),
    ],
)
def test_the_stored_category_is_sent_in_the_providers_spelling(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
    stored: str,
    sent: str,
) -> None:
    """The business row holds our lower-case value, never Meta's word."""
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=dataclasses.replace(business, special_ad_category=stored),
        catalog=catalog,
        currency="USD",
    )

    assert built.special_ad_categories == (sent,)


def test_a_category_names_the_country_it_runs_in(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """Aimed at a pin, the targeting names no country; the business's is it."""
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=dataclasses.replace(
            business, special_ad_category="housing", country_code="uz"
        ),
        catalog=catalog,
        currency="USD",
        geo=GeoChoice(mode="around", lat="41.3", lng="69.2", radius_km=25),
    )

    assert built.special_ad_category_countries == ("UZ",)


def test_a_country_wide_campaign_names_its_own_country(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=dataclasses.replace(
            business, special_ad_category="employment", country_code="UZ"
        ),
        catalog=catalog,
        currency="USD",
        geo=GeoChoice(mode="country", country_code="KZ"),
    )

    assert built.special_ad_category_countries == ("KZ",)


def test_no_category_names_no_country(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=dataclasses.replace(business, country_code="UZ"),
        catalog=catalog,
        currency="USD",
    )

    assert built.special_ad_category_countries == ()


def test_an_unknown_category_is_refused_before_anything_is_sent(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    with pytest.raises(InvalidTargeting):
        build(
            provider=PROVIDER,
            answers=answers,
            business=dataclasses.replace(business, special_ad_category="gambling"),
            catalog=catalog,
            currency="USD",
        )


def test_the_preset_that_built_it_travels_with_it(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """Presets change; running ad sets do not. Months later this is the
    only way to explain why an ad set targets what it targets."""
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert built.preset_key == "restaurant/calls"
    # Pinned as a literal on purpose. A catalogue edit that changes what a
    # preset builds has to bump this, and a test that read the version back
    # out of the catalogue would agree with any number at all - including
    # the one that quietly left two different specs both calling themselves
    # version 1. Version 2 dropped the retired Facebook video feed
    # placement; version 3 turned Advantage+ audience off, because it
    # demotes the approved age and interests to suggestions and refuses a
    # hard age_max under 65; version 4 gave all twelve files the same five
    # goals in the same order and withdrew the sale; version 5 put the call
    # goal under the traffic objective; version 6 added a request left on
    # the advertiser's own site.
    assert built.preset_version == "6"


def test_the_budget_stays_a_whole_number_of_minor_units(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, daily_budget_minor=MinorUnits(123_456)),
        business=business,
        catalog=catalog,
        currency="USD",
    )

    assert built.daily_budget_minor == 123_456
    assert isinstance(built.daily_budget_minor, int)
    assert built.currency == "USD"


def test_a_business_with_no_pin_says_which_field_is_missing(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """The screen turns this into "mark your location on the map"."""
    with pytest.raises(UnfilledTemplate) as caught:
        build(
            provider=PROVIDER,
            answers=answers,
            business=dataclasses.replace(business, lat=""),
            catalog=catalog,
            currency="USD",
        )

    assert caught.value.placeholder == "business.lat"


def test_a_country_wide_category_needs_no_pin(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """An online shop delivers past the end of any radius."""
    built = build(
        provider=PROVIDER,
        answers=dataclasses.replace(answers, category="ecommerce", goal="sales"),
        business=dataclasses.replace(business, category="ecommerce", lat="", lng=""),
        catalog=catalog,
        currency="USD",
    )

    assert built.targeting["geo_locations"] == {"countries": ["UZ"]}


def test_a_business_with_no_pin_can_still_build(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """A shop that never marked itself on a map is a normal shop.

    Refusing here would put a wall in front of most of the catalogue. A
    country is a wider audience than a radius and an honest one.
    """
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=dataclasses.replace(business, lat="", lng=""),
        catalog=catalog,
        currency="USD",
        geo=fallback(country_code="UZ"),
    )

    assert built.targeting["geo_locations"] == {"countries": ["UZ"]}


def test_the_missing_pin_is_reported_rather_than_hidden(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """The audience got wider than the preset intended. Say so."""
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=dataclasses.replace(business, lat="", lng=""),
        catalog=catalog,
        currency="USD",
        geo=fallback(country_code="UZ"),
    )

    assert ("geo_locations", "location_missing") in tuple(
        (a.field, a.reason) for a in built.adjustments
    )


def test_the_override_replaces_the_block_whole(
    catalog: PresetCatalog,
    answers: OnboardingAnswers,
    business: BusinessProfile,
) -> None:
    """Merging a country into a radius would target both, which is neither."""
    built = build(
        provider=PROVIDER,
        answers=answers,
        business=business,
        catalog=catalog,
        currency="USD",
        geo=fallback(country_code="UZ"),
    )

    assert "custom_locations" not in built.targeting["geo_locations"]
