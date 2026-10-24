"""The events a website campaign may be bought against, and what they build.

The provider demands a dataset and an event together and refuses either
half alone, so what is pinned here is that the table can only produce
pairs it will accept - and that an answer nobody recognises leaves the
catalogue's own event in place rather than sending a name at all.
"""

from adskit import MinorUnits

from core.targeting import (
    CONVERSION_EVENTS,
    EVENT_KEY,
    REQUEST_EVENTS,
    SNIPPET_EVENTS,
    BuiltTargeting,
    BusinessProfile,
    ConversionSource,
    OnboardingAnswers,
    PresetCatalog,
    build,
    conversion_event,
    conversion_events,
    counts_a_request,
    event_for_snippet,
    events_for,
    fallback,
)
from core.targeting.presets import CATALOG_DIR

PROVIDER = "meta"
CATALOG = PresetCatalog.from_directory(CATALOG_DIR)


def built(event: str = "") -> BuiltTargeting:
    return build(
        provider=PROVIDER,
        answers=OnboardingAnswers(
            category="services",
            goal="site_leads",
            daily_budget_minor=MinorUnits(5000),
            conversion_event=event,
        ),
        business=BusinessProfile(name="Osh", category="services", country_code="UZ"),
        catalog=CATALOG,
        currency="USD",
        geo=fallback(country_code="UZ"),
        conversion=ConversionSource(external_id="777", name="Sayt"),
        link="https://osh.uz",
    )


# --- The table -----------------------------------------------------------
def test_no_event_is_listed_twice() -> None:
    keys = [row.key for row in CONVERSION_EVENTS]

    assert len(keys) == len(set(keys))


def test_the_provider_names_are_its_screen_words_not_its_api_words() -> None:
    """Drawn beside the owner's words, so never ``COMPLETE_REGISTRATION``."""
    spelled_like_the_api = {
        row.key
        for row in CONVERSION_EVENTS
        if "_" in row.provider_label or row.provider_label.isupper()
    }

    assert spelled_like_the_api == set()


def test_a_request_is_told_from_a_look() -> None:
    asking = conversion_event(provider=PROVIDER, key="SUBMIT_APPLICATION")
    looking = conversion_event(provider=PROVIDER, key="CONTENT_VIEW")

    assert asking is not None and looking is not None
    assert counts_a_request(asking) is True
    assert counts_a_request(looking) is False


def test_every_request_event_is_one_the_table_offers() -> None:
    """A rule may only prefer events somebody can actually be given."""
    offered = {row.key for row in conversion_events(provider=PROVIDER)}

    assert offered >= REQUEST_EVENTS


def test_every_name_a_tag_fires_maps_onto_an_event_that_exists() -> None:
    offered = {row.key for row in CONVERSION_EVENTS}

    assert set(SNIPPET_EVENTS.values()) <= offered


def test_the_two_vocabularies_are_crossed_rather_than_transliterated() -> None:
    """The provider spells the same event differently in the two places."""
    found = event_for_snippet(provider=PROVIDER, name="ViewContent")

    assert found is not None
    assert found.key == "CONTENT_VIEW"


def test_a_page_view_is_not_something_to_buy() -> None:
    """Every tag fires it on every page and no ad set can name it."""
    assert event_for_snippet(provider=PROVIDER, name="PageView") is None


# --- What a choice builds ------------------------------------------------
def test_nobody_choosing_builds_the_catalogues_own_event() -> None:
    assert built().promoted_object[EVENT_KEY] == "LEAD"


def test_a_chosen_event_is_what_the_ad_set_names() -> None:
    spec = built("SCHEDULE")

    assert spec.promoted_object[EVENT_KEY] == "SCHEDULE"
    assert spec.promoted_object["pixel_id"] == "777"


def test_an_event_the_provider_has_no_word_for_changes_nothing() -> None:
    """The provider refuses an unknown name with the ad set half made."""
    assert built("WHATEVER").promoted_object[EVENT_KEY] == "LEAD"


def test_an_event_the_objective_does_not_take_changes_nothing() -> None:
    """Meta refuses a purchase bought under the leads objective."""
    assert built("PURCHASE").promoted_object[EVENT_KEY] == "LEAD"


def test_each_objective_offers_only_its_own_events() -> None:
    leads = {
        row.key for row in events_for(provider=PROVIDER, objective="OUTCOME_LEADS")
    }
    sales = {
        row.key for row in events_for(provider=PROVIDER, objective="OUTCOME_SALES")
    }

    assert "LEAD" in leads and "PURCHASE" not in leads
    assert "PURCHASE" in sales and "LEAD" not in sales


def test_a_goal_the_provider_counts_itself_names_no_event() -> None:
    """A form the provider hosts has nothing on anybody's website to read."""
    spec = build(
        provider=PROVIDER,
        answers=OnboardingAnswers(
            category="services",
            goal="leads",
            daily_budget_minor=MinorUnits(5000),
            conversion_event="PURCHASE",
        ),
        business=BusinessProfile(name="Osh", category="services", country_code="UZ"),
        catalog=CATALOG,
        currency="USD",
        geo=fallback(country_code="UZ"),
    )

    assert EVENT_KEY not in spec.promoted_object
