"""The table of kinds each goal may be bought as, and what choosing one builds."""

import pytest
from adskit import MinorUnits

from core.targeting import (
    CAMPAIGN_TYPES,
    BuiltTargeting,
    BusinessProfile,
    ConversionSource,
    OnboardingAnswers,
    PresetCatalog,
    build,
    campaign_type,
    fallback,
    type_built_as,
    types_for,
)
from core.targeting.campaign_types import CampaignType, ShapeIndex
from core.targeting.compat import OFFERS, Offer
from core.targeting.presets import CATALOG_DIR

PROVIDER = "meta"
CATALOG = PresetCatalog.from_directory(CATALOG_DIR)


def every_preset() -> list:  # type: ignore[type-arg]
    return [
        preset
        for category in CATALOG.categories(provider=PROVIDER)
        for preset in CATALOG.goals(provider=PROVIDER, category=category.key)
    ]


def built(goal: str, kind: str = "") -> BuiltTargeting:
    return build(
        provider=PROVIDER,
        answers=OnboardingAnswers(
            category="restaurant",
            goal=goal,
            daily_budget_minor=MinorUnits(1000),
            campaign_type=kind,
        ),
        business=BusinessProfile(name="Osh", category="restaurant", country_code="UZ"),
        catalog=CATALOG,
        currency="USD",
        geo=fallback(country_code="UZ"),
        # The goals that report from the advertiser's own site are built
        # here too, and without this they build the shape of a launch with
        # nothing plugged in yet.
        conversion=ConversionSource(external_id="777", name="Sayt"),
        link="https://osh.uz",
    )


# --- The table -----------------------------------------------------------
def test_no_key_is_used_twice() -> None:
    """A key stored for one goal must never read as a choice for another."""
    keys = [row.key for row in CAMPAIGN_TYPES]

    assert len(keys) == len(set(keys))


def test_no_two_kinds_share_the_provider_words() -> None:
    """What a running campaign was built as is read back from these words."""
    shapes = [
        (row.provider, row.objective, row.destination_type, row.optimization_goal)
        for row in CAMPAIGN_TYPES
    ]

    assert len(shapes) == len(set(shapes))


def test_a_running_campaign_is_named_after_its_row() -> None:
    found = type_built_as(
        provider=PROVIDER,
        objective="OUTCOME_ENGAGEMENT",
        destination_type="PHONE_CALL",
        optimization_goal="QUALITY_CALL",
    )

    assert found is not None
    assert found.key == "calls_engaged"


def test_a_pairing_outside_the_table_is_not_guessed() -> None:
    assert (
        type_built_as(
            provider=PROVIDER,
            objective="OUTCOME_SALES",
            destination_type="",
            optimization_goal="QUALITY_CALL",
        )
        is None
    )


# --- Reading back: every row on offer, as it read before destinations -----
# What each row read back as while the read-back was keyed on two words,
# taken from that code. Written out so a later row cannot move it.
BEFORE: dict[str, str | None] = {
    "form_leads": "form_leads",
    "form_quality_leads": None,
    "site_requests": "site_requests",
    "site_requests_views": "site_requests_views",
    "site_requests_clicks": "site_requests_clicks",
    "site_requests_reach": "site_requests_reach",
    "calls_many": "calls_many",
    "calls_engaged": "calls_engaged",
    "calls_ready": "calls_ready",
    "chat_conversations": "chat_conversations",
    "chat_link_clicks": "chat_link_clicks",
    "site_page_views": "site_page_views",
    "site_link_clicks": "site_link_clicks",
    "site_daily_reach": "site_daily_reach",
    "site_impressions": "site_impressions",
    "seen_widely": "seen_widely",
    "seen_often": "seen_often",
    "seen_remembered": "seen_remembered",
}

# Every word an ad set of an existing row may hold for where it lands,
# the read-mode blank included.
STORED_DESTINATIONS = (
    "",
    "UNDEFINED",
    "WEBSITE",
    "ON_AD",
    "PHONE_CALL",
    "MESSENGER",
    "INSTAGRAM_DIRECT",
    "WHATSAPP",
)


# The rows that were on offer while the read-back was keyed on two words.
BEFORE_OFFERS = tuple(offer for offer in OFFERS if offer.key in BEFORE)


@pytest.mark.parametrize("offer", BEFORE_OFFERS, ids=lambda offer: offer.key)
@pytest.mark.parametrize("destination", STORED_DESTINATIONS)
def test_every_row_on_offer_reads_back_as_before(
    offer: Offer, destination: str
) -> None:
    """Old launches keep their name whatever destination Meta stored."""
    found = type_built_as(
        provider=offer.provider,
        objective=offer.kind.objective,
        destination_type=destination,
        optimization_goal=offer.kind.optimization_goal,
    )

    assert (found.key if found else None) == BEFORE[offer.key]


def test_a_quality_form_still_reads_back_as_nothing() -> None:
    """Not a kind anybody ticks, so the page never named it - nor does it now."""
    assert (
        type_built_as(
            provider=PROVIDER,
            objective="OUTCOME_LEADS",
            destination_type="ON_AD",
            optimization_goal="QUALITY_LEAD",
        )
        is None
    )


# A row landing where no preset does, as the profile visit will. Bought on
# link clicks here on purpose: the one pairing it would otherwise share.
PROFILE = CampaignType(
    "meta",
    "profile",
    "profile_visits",
    "OUTCOME_TRAFFIC",
    "LINK_CLICKS",
    "Traffic",
    "Maximize number of link clicks",
    "traffic",
    destination_type="INSTAGRAM_PROFILE",
)
WITH_PROFILE = ShapeIndex.of((*CAMPAIGN_TYPES, PROFILE))


def test_a_claimed_destination_is_read_as_its_own_row() -> None:
    found = WITH_PROFILE.find(
        provider=PROVIDER,
        objective="OUTCOME_TRAFFIC",
        destination_type="INSTAGRAM_PROFILE",
        optimization_goal="LINK_CLICKS",
    )

    assert found is PROFILE


def test_a_claimed_destination_never_falls_to_a_row_without_one() -> None:
    """A profile visit bought on page views is nobody's, not a site visit."""
    assert (
        WITH_PROFILE.find(
            provider=PROVIDER,
            objective="OUTCOME_TRAFFIC",
            destination_type="INSTAGRAM_PROFILE",
            optimization_goal="LANDING_PAGE_VIEWS",
        )
        is None
    )


@pytest.mark.parametrize("destination", STORED_DESTINATIONS)
def test_a_site_visit_on_clicks_is_still_a_site_visit(destination: str) -> None:
    found = WITH_PROFILE.find(
        provider=PROVIDER,
        objective="OUTCOME_TRAFFIC",
        destination_type=destination,
        optimization_goal="LINK_CLICKS",
    )

    assert found is not None
    assert found.key == "site_link_clicks"


@pytest.mark.parametrize("offer", BEFORE_OFFERS, ids=lambda offer: offer.key)
@pytest.mark.parametrize("destination", STORED_DESTINATIONS)
def test_a_new_row_changes_no_existing_read_back(
    offer: Offer, destination: str
) -> None:
    words = {
        "provider": offer.provider,
        "objective": offer.kind.objective,
        "destination_type": destination,
        "optimization_goal": offer.kind.optimization_goal,
    }

    assert WITH_PROFILE.find(**words) == type_built_as(**words)


def test_the_provider_names_are_its_screen_words_not_its_api_words() -> None:
    """Shown beside the owner's words, so never ``OUTCOME_TRAFFIC``."""
    spelled_like_the_api = {
        row.key
        for row in CAMPAIGN_TYPES
        if "_" in row.provider_label
        or row.provider_label.isupper()
        or "_" in row.provider_goal_label
    }

    assert spelled_like_the_api == set()


def test_every_goal_on_offer_can_be_bought_some_way() -> None:
    missing = {
        preset.key
        for preset in every_preset()
        if preset.offered
        and preset.is_deliverable
        and not types_for(provider=PROVIDER, goal=preset.goal)
    }

    assert missing == set()


def test_the_default_is_what_the_preset_already_builds() -> None:
    """A launch that never chose must build exactly what it built before."""
    wrong = {
        preset.key: (preset.objective, preset.optimization_goal)
        for preset in every_preset()
        if (found := types_for(provider=PROVIDER, goal=preset.goal))
        and (found[0].objective, found[0].optimization_goal)
        != (preset.objective, preset.optimization_goal)
    }

    assert wrong == {}


def test_calls_may_be_bought_three_ways() -> None:
    kinds = types_for(provider=PROVIDER, goal="calls")

    assert [row.objective for row in kinds] == [
        "OUTCOME_TRAFFIC",
        "OUTCOME_ENGAGEMENT",
        "OUTCOME_LEADS",
    ]


def test_a_key_chosen_for_another_goal_reads_as_the_default() -> None:
    found = campaign_type(provider=PROVIDER, goal="traffic", key="calls_ready")

    assert found is not None
    assert found.key == "site_page_views"


def test_a_goal_the_table_does_not_cover_has_no_kind() -> None:
    assert campaign_type(provider=PROVIDER, goal="sales", key="") is None


# --- What a choice builds ------------------------------------------------
def test_nobody_choosing_builds_the_default() -> None:
    spec = built("calls")

    assert (spec.objective, spec.campaign_type) == ("OUTCOME_TRAFFIC", "calls_many")


def test_a_chosen_kind_changes_the_objective_and_nothing_about_the_ad() -> None:
    default, engaged = built("calls"), built("calls", "calls_engaged")

    assert (engaged.objective, engaged.optimization_goal) == (
        "OUTCOME_ENGAGEMENT",
        "QUALITY_CALL",
    )
    assert engaged.destination_type == default.destination_type == "PHONE_CALL"
    assert engaged.call_to_action == default.call_to_action
    assert engaged.campaign_type == "calls_engaged"


def test_a_site_visit_can_be_bought_on_taps_of_the_link() -> None:
    assert built("traffic", "site_link_clicks").optimization_goal == "LINK_CLICKS"


def test_a_website_request_may_be_bought_four_ways() -> None:
    """The provider's own screen offers all four under this location."""
    kinds = types_for(provider=PROVIDER, goal="site_leads")

    assert [row.optimization_goal for row in kinds] == [
        "OFFSITE_CONVERSIONS",
        "LANDING_PAGE_VIEWS",
        "LINK_CLICKS",
        "REACH",
    ]


def test_a_request_bought_on_clicks_still_names_the_pixel() -> None:
    """The dataset is the conversion location, not the performance goal.

    An ad set delivering on clicks is still a website-request campaign, and
    dropping the pixel would leave the provider with nothing to count the
    result it was asked for.
    """
    spec = built("site_leads", "site_requests_clicks")

    assert spec.optimization_goal == "LINK_CLICKS"
    assert "pixel_id" in spec.promoted_object
    assert spec.needs_conversion_source is True


def test_a_form_is_never_offered_bought_on_clicks() -> None:
    """The one pairing the screen offers that this table refuses to carry."""
    clicks = {
        row.key
        for row in types_for(provider=PROVIDER, goal="leads")
        if row.optimization_goal == "LINK_CLICKS"
    }

    assert clicks == set()


def test_being_seen_can_be_bought_on_reach() -> None:
    assert built("views", "seen_widely").optimization_goal == "REACH"


def test_a_choice_left_over_from_another_goal_builds_the_default() -> None:
    spec = built("traffic", "calls_ready")

    assert (spec.objective, spec.campaign_type) == (
        "OUTCOME_TRAFFIC",
        "site_page_views",
    )


def test_the_reference_covers_every_row_on_offer_but_the_profile() -> None:
    assert set(BEFORE) == {offer.key for offer in OFFERS} - {"profile_visits"}


# --- The profile visit, read back by where it lands ----------------------
def profile_read(destination: str, goal: str) -> str | None:
    found = type_built_as(
        provider=PROVIDER,
        objective="OUTCOME_TRAFFIC",
        destination_type=destination,
        optimization_goal=goal,
    )
    return found.key if found else None


def test_a_profile_visit_is_named_after_its_row() -> None:
    assert profile_read("INSTAGRAM_PROFILE", "PROFILE_VISIT") == "profile_visits"


def test_a_profile_ad_set_on_link_clicks_is_never_a_site_visit() -> None:
    """Meta keeps this pairing (probe, 2026-09-28) - it is nobody's row."""
    assert profile_read("INSTAGRAM_PROFILE", "LINK_CLICKS") is None


def test_a_site_visit_on_link_clicks_still_is_one() -> None:
    assert profile_read("", "LINK_CLICKS") == "site_link_clicks"


@pytest.mark.parametrize("destination", STORED_DESTINATIONS)
def test_profile_visits_elsewhere_are_not_guessed(destination: str) -> None:
    assert profile_read(destination, "PROFILE_VISIT") is None
