"""Goals that optimise for a sale on the advertiser's own website.

Two of the twelve categories sell one, and neither is buildable without a
pixel: Meta refuses an ad set optimising for ``OFFSITE_CONVERSIONS``
without a ``promoted_object``, and a goal offered without one would fail
while the campaign was being created.

The rule under test is the split between building and launching. A spec
whose pixel is missing is still built, still shown, still editable - and
still refused at the gate.
"""

import pytest

from core.targeting import (
    BusinessProfile,
    ConversionSource,
    ConversionSourceMissing,
    NoInterestsChosen,
    OnboardingAnswers,
    build,
    fallback,
    validate_launchable,
)
from core.targeting.presets import CATALOG_DIR, PresetCatalog

CATALOG = PresetCatalog.from_directory(CATALOG_DIR)
PIXEL = ConversionSource(external_id="123456789", name="Do'kon pixeli")

SHOP = BusinessProfile(
    name="Do'kon",
    category="ecommerce",
    country_code="UZ",
    city="Tashkent",
)


def answers(goal: str = "sales", **extra: object) -> OnboardingAnswers:
    fields: dict[str, object] = {
        "category": "ecommerce",
        "goal": goal,
        "daily_budget_minor": 1000,
        # Pinned, because the interest gate is not what this file is
        # about and the default mode does not require one.
        "targeting_mode": "interests",
    }
    return OnboardingAnswers(**(fields | extra))  # type: ignore[arg-type]


# Both goals in this file send somebody to a website, so both need one -
# a gate this file is not about, and one that would otherwise refuse every
# case here before the pixel rule was ever reached.
SITE = "https://dokon.uz/"


def built(goal: str = "sales", conversion: ConversionSource | None = None):
    return build(
        provider="meta",
        answers=answers(goal),
        business=SHOP,
        catalog=CATALOG,
        currency="USD",
        conversion=conversion,
        geo=fallback(country_code="UZ"),
        link=SITE,
    )


# --- What the preset asks for --------------------------------------------
def test_a_sales_goal_says_it_needs_somewhere_to_report_sales() -> None:
    assert built().needs_conversion_source is True


def test_a_lead_goal_asks_for_nothing_of_the_kind() -> None:
    """Most goals measure inside the provider. Half the businesses this is
    for have no website to put a tag on."""
    spec = built("traffic")

    assert spec.needs_conversion_source is False
    assert spec.promoted_object == {}


# --- With a pixel --------------------------------------------------------
def test_the_pixel_id_is_filled_from_the_source_not_the_catalogue() -> None:
    """The catalogue ships a placeholder. An id in a YAML file would be one
    customer's pixel in every customer's campaign."""
    spec = built(conversion=PIXEL)

    assert spec.promoted_object == {
        "pixel_id": "123456789",
        "custom_event_type": "PURCHASE",
    }


def test_a_filled_spec_passes_the_gate() -> None:
    spec = build(
        provider="meta",
        answers=answers(),
        business=SHOP,
        catalog=CATALOG,
        currency="USD",
        conversion=PIXEL,
        geo=fallback(country_code="UZ"),
        link=SITE,
    )
    # Interests are the other gate and are not what this file is about.
    with pytest.raises(NoInterestsChosen):
        validate_launchable(spec)


# --- Without one ---------------------------------------------------------
def test_a_missing_pixel_still_builds_a_spec_somebody_can_read() -> None:
    """Refusing at build time would stop an owner seeing their own proposal
    because of a thing they plug in afterwards."""
    spec = built()

    assert spec.targeting
    assert spec.promoted_object == {}


def test_a_missing_pixel_is_reported_rather_than_hidden() -> None:
    spec = built()

    reasons = [note.reason for note in spec.adjustments]
    assert "conversion_source_missing" in reasons


def test_a_missing_pixel_refuses_at_the_gate() -> None:
    """Meta would refuse it anyway. Letting it through only moves the
    refusal somewhere the message is Meta's rather than ours."""
    with pytest.raises(ConversionSourceMissing):
        validate_launchable(built())


def test_an_empty_source_counts_as_none() -> None:
    """A promoted_object with a blank pixel id is the shape the provider
    accepts and then refuses to deliver on."""
    spec = built(conversion=ConversionSource(external_id=""))

    assert spec.promoted_object == {}
    with pytest.raises(ConversionSourceMissing):
        validate_launchable(spec)


def test_the_pixel_gate_is_checked_before_the_interest_one() -> None:
    """It is the one the owner can act on right now: plugging a pixel in is
    a screen away, while an unconfirmed interest needs a lookup to re-run."""
    with pytest.raises(ConversionSourceMissing):
        validate_launchable(built())


def test_a_goal_needing_nothing_is_never_stopped_by_this_rule() -> None:
    spec = built("traffic")

    with pytest.raises(NoInterestsChosen):
        validate_launchable(spec)


# --- A request left on the site ------------------------------------------
def test_a_request_on_the_site_is_a_lead_the_pixel_reports() -> None:
    spec = built("site_leads", conversion=PIXEL)

    assert spec.objective == "OUTCOME_LEADS"
    assert spec.needs_lead_form is False
    assert spec.promoted_object == {
        "pixel_id": "123456789",
        "custom_event_type": "LEAD",
    }


def test_a_request_on_the_site_without_a_pixel_is_refused_at_the_gate() -> None:
    with pytest.raises(ConversionSourceMissing):
        validate_launchable(built("site_leads"))
