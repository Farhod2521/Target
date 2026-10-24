"""The first step's table: every row, where it sits, and what closes it."""

import pytest
from adskit import MinorUnits

from core.targeting import (
    CAMPAIGN_TYPES,
    OFFERS,
    OUTCOMES,
    AccountFacts,
    BusinessProfile,
    ConversionSource,
    OnboardingAnswers,
    PresetCatalog,
    build,
    choices_for,
    closed_by,
    default_offer,
    fallback,
    is_open,
    listed_for,
    nearest_open,
    needs_pixel,
    offer,
    offers_for,
    outcome_default,
    outcome_of,
    types_for,
)
from core.targeting.presets import CATALOG_DIR

PROVIDER = "meta"
CATALOG = PresetCatalog.from_directory(CATALOG_DIR)
NO_PIXEL = AccountFacts(has_pixel=False)
WITH_PIXEL = AccountFacts(has_pixel=True)

# Every goal and kind a launch in production has ever been saved with,
# read from the catalogue's and the table's git history.
EVERY_STORED_GOAL = (
    "leads",
    "messages",
    "calls",
    "views",
    "traffic",
    "site_leads",
    "sales",
    "store_visits",
    "awareness",
)
EVERY_STORED_KIND = tuple(row.key for row in CAMPAIGN_TYPES)


def row(key: str):  # type: ignore[no-untyped-def]
    found = offer(provider=PROVIDER, key=key)
    assert found is not None, key
    return found


# --- Integrity ------------------------------------------------------------
def test_every_kind_is_exactly_one_buildable_row() -> None:
    """What is chosen on the first step is what the builder buys."""
    buildable = [item.key for item in OFFERS if item.buildable]

    assert sorted(buildable) == sorted(EVERY_STORED_KIND)
    assert len(buildable) == len(set(buildable))


def test_a_row_that_cannot_be_built_is_not_a_kind() -> None:
    """Nothing anybody may tick names a row the sequence cannot create."""
    kinds = {kind.key for kind in CAMPAIGN_TYPES}

    assert all(item.key not in kinds for item in OFFERS if not item.buildable)


def test_row_keys_are_unique() -> None:
    keys = [item.key for item in OFFERS]

    assert len(keys) == len(set(keys))


def test_every_row_belongs_to_its_outcomes_goals() -> None:
    goals = {spec.key: spec.goals for spec in OUTCOMES}

    for item in OFFERS:
        assert item.goal in goals[item.outcome], item.key


def test_every_live_outcome_has_rows_and_a_buildable_default() -> None:
    for spec in OUTCOMES:
        if not spec.live:
            assert outcome_default(provider=PROVIDER, outcome=spec.key) is None
            continue
        default = outcome_default(provider=PROVIDER, outcome=spec.key)
        assert default is not None and default.buildable, spec.key
        assert offers_for(provider=PROVIDER, outcome=spec.key)


def test_the_second_questions_options_are_rows_of_their_own() -> None:
    """A row's plain choice is itself a row, under the same outcome."""
    for item in OFFERS:
        if not item.choice:
            continue
        parent = row(item.choice)
        assert parent.is_choice
        assert parent.outcome == item.outcome


def test_the_second_question_is_what_the_owner_asked_for() -> None:
    def keys(outcome: str) -> list[str]:
        return [item.key for item in choices_for(provider=PROVIDER, outcome=outcome)]

    assert keys("requests") == ["form_leads", "site_requests"]
    assert keys("calls") == ["calls_many"]
    assert keys("messages") == ["chat_conversations"]
    assert keys("visits") == ["site_page_views", "site_link_clicks"]
    assert keys("reach") == ["seen_widely", "seen_often", "seen_remembered"]


def test_the_defaults_are_the_tables_own() -> None:
    """What the first step opens on, and what a launch that never chose is
    built as. The two differ only for being seen: Reach is recommended from
    now on, while a launch saved without a kind keeps building Impressions."""
    expected = {
        "requests": "form_leads",
        "calls": "calls_many",
        "messages": "chat_conversations",
        "visits": "site_page_views",
        "reach": "seen_widely",
    }
    for outcome, key in expected.items():
        default = outcome_default(provider=PROVIDER, outcome=outcome)
        assert default is not None and default.key == key
    assert default_offer(provider=PROVIDER, goal="views") == row("seen_often")
    for item in OFFERS:
        if item.buildable:
            kinds = types_for(provider=PROVIDER, goal=item.goal)
            assert default_offer(provider=PROVIDER, goal=item.goal) == row(kinds[0].key)


def test_the_meta_labels_are_names_not_api_words() -> None:
    for item in OFFERS:
        for label in (
            item.kind.provider_label,
            item.kind.provider_goal_label,
            item.provider_destination_label,
        ):
            assert "_" not in label and not label.isupper(), item.key


def test_every_row_tells_the_model_what_it_means() -> None:
    for item in OFFERS:
        assert item.meaning and item.phrases, item.key


HIDDEN = {
    "form_quality_leads",
    "site_requests_views",
    "site_requests_clicks",
    "site_requests_reach",
}


def test_rows_no_longer_offered_are_not_listed() -> None:
    listed = {
        item.key
        for spec in OUTCOMES
        for item in listed_for(provider=PROVIDER, outcome=spec.key)
    }

    assert HIDDEN.isdisjoint(listed)
    assert {item.key for item in OFFERS} - HIDDEN == listed


@pytest.mark.parametrize("key", sorted(HIDDEN))
def test_a_launch_holding_one_still_finds_it(key: str) -> None:
    item = row(key)

    kept = listed_for(provider=PROVIDER, outcome=item.outcome, keep=key)

    assert item in kept


def test_calls_are_one_option_and_the_other_two_are_meta_settings() -> None:
    assert row("calls_engaged").choice == ""
    assert row("calls_ready").choice == ""
    assert {item.key for item in listed_for(provider=PROVIDER, outcome="calls")} == {
        "calls_many",
        "calls_engaged",
        "calls_ready",
    }


def test_no_two_options_of_one_answer_share_a_grey_name() -> None:
    """The second question's grey line names the performance goal too."""
    for spec in OUTCOMES:
        names = [
            " · ".join(
                part
                for part in (
                    item.kind.provider_label,
                    item.provider_destination_label,
                    item.kind.provider_goal_name,
                )
                if part
            )
            for item in choices_for(provider=PROVIDER, outcome=spec.key)
        ]
        assert len(names) == len(set(names)), spec.key


def test_every_goal_has_a_short_name() -> None:
    for item in OFFERS:
        assert item.kind.provider_goal_name != item.kind.provider_goal_label, item.key


# --- Old answers ----------------------------------------------------------
@pytest.mark.parametrize("goal", EVERY_STORED_GOAL)
def test_every_stored_goal_reads_without_raising(goal: str) -> None:
    spec = outcome_of(goal)

    if goal in {"store_visits", "awareness"}:
        assert spec is None
    else:
        assert spec is not None and goal in spec.goals


@pytest.mark.parametrize("key", EVERY_STORED_KIND)
def test_every_stored_kind_has_a_row_under_its_goals_outcome(key: str) -> None:
    item = row(key)
    spec = outcome_of(item.goal)

    assert spec is not None and spec.key == item.outcome


def test_sales_is_shown_and_closed() -> None:
    spec = outcome_of("sales")

    assert spec is not None and not spec.live


# --- What closes a row ----------------------------------------------------
def test_a_site_request_needs_a_pixel() -> None:
    for key in (
        "site_requests",
        "site_requests_views",
        "site_requests_clicks",
        "site_requests_reach",
    ):
        assert closed_by(row(key), NO_PIXEL) == ("pixel",)
        assert is_open(row(key), WITH_PIXEL)
        assert needs_pixel(provider=PROVIDER, key=key)


def test_a_visit_needs_no_pixel() -> None:
    assert is_open(row("site_page_views"), NO_PIXEL)
    assert not needs_pixel(provider=PROVIDER, key="site_page_views")


def test_quality_leads_stay_closed_whatever_the_account_has() -> None:
    quality = row("form_quality_leads")

    assert closed_by(quality, WITH_PIXEL) == ("quality_signal",)
    assert closed_by(quality, AccountFacts(has_pixel=True, quality_ready=True)) == (
        "not_built",
    )


def test_a_closed_row_is_offered_the_nearest_open_one_in_its_outcome() -> None:
    assert nearest_open(row("site_requests"), NO_PIXEL).key == "form_leads"  # type: ignore[union-attr]
    assert nearest_open(row("form_quality_leads"), NO_PIXEL).key == "form_leads"  # type: ignore[union-attr]
    assert nearest_open(row("site_requests_views"), WITH_PIXEL).key == (  # type: ignore[union-attr]
        "site_requests"
    )


def test_a_named_alternative_wins_only_inside_the_outcome() -> None:
    blocked = row("site_requests")

    assert nearest_open(blocked, NO_PIXEL, preferred=("calls_many",)).key == (  # type: ignore[union-attr]
        "form_leads"
    )


# --- The gate reads the table --------------------------------------------
@pytest.mark.parametrize("key", EVERY_STORED_KIND)
def test_the_built_spec_asks_for_a_pixel_exactly_when_the_row_does(key: str) -> None:
    item = row(key)
    built = build(
        provider=PROVIDER,
        answers=OnboardingAnswers(
            category="restaurant",
            goal=item.goal,
            daily_budget_minor=MinorUnits(1000),
            campaign_type=key,
        ),
        business=BusinessProfile(name="Osh", category="restaurant", country_code="UZ"),
        catalog=CATALOG,
        currency="USD",
        geo=fallback(country_code="UZ"),
        conversion=ConversionSource(external_id="777", name="Sayt"),
        link="https://osh.uz",
    )

    assert built.needs_conversion_source is ("pixel" in item.needs)
    assert built.campaign_type == key
