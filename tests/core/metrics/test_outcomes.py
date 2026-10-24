"""What one result is, per optimisation goal.

The sweep at the top is the important test in this file. A goal the
product sells that is in no table here - not in the lead list, not among
the counted results, not among the sentences - is a campaign that spends
money and shows its owner a nought with nothing beside it, which is the
exact failure every note in ``core.metrics.outcomes`` says it exists to
prevent.

A goal is data: it arrives from a YAML file nobody type-checks and nobody
reviews as code. The only thing between a preset added next month and a
screen that goes silent about it is a test that reads the catalogue.
"""

import pytest

from core.metrics import LEAD_GOALS, counts_leads
from core.metrics.outcomes import (
    OUTCOMES,
    campaign_goal,
    is_counted,
    outcome_for,
    outcome_of,
)
from core.targeting.loader import read_directory
from core.targeting.presets import CATALOG_DIR

# The offered goals whose result this product cannot count yet: a purchase
# on the advertiser's own website, counted by a pixel there is no table for,
# and a visit to the Instagram profile, whose count has not been read off a
# live ad set. Named so the sweep below can be a sweep rather than a list
# with an exception buried in it.
NO_FIGURE = frozenset({"OFFSITE_CONVERSIONS"})


@pytest.fixture(scope="module")
def offered() -> frozenset[str]:
    """Every optimisation goal the preset catalogue actually sells."""
    _, presets = read_directory(CATALOG_DIR)
    return frozenset(preset.optimization_goal for preset in presets)


# --- The sweep -----------------------------------------------------------
def test_every_goal_the_catalogue_offers_is_named(offered: frozenset[str]) -> None:
    """A goal this product sells and then cannot describe is a campaign
    whose owner is shown a nought with no sentence beside it."""
    assert offered <= set(OUTCOMES), sorted(offered - set(OUTCOMES))


def test_every_goal_but_the_sales_one_has_a_figure(offered: frozenset[str]) -> None:
    """Countable is the ordinary case and uncountable is the exception, and
    naming the exception is what keeps it from growing quietly."""
    for goal in offered:
        assert is_counted(goal) is (goal not in NO_FIGURE), goal


def test_the_catalogue_still_offers_the_sales_goal(offered: frozenset[str]) -> None:
    """The exception above is only worth writing while it exists. Dropped
    from the catalogue, the test that names it would keep passing over
    nothing."""
    assert offered >= NO_FIGURE


# --- The table itself ----------------------------------------------------
def test_only_a_form_on_the_ad_produces_a_lead_row_here() -> None:
    """Derived from the table rather than declared beside it, and this pins
    that the derivation lands on the same two goals. Both mean the same
    thing: a form the provider hosts, whose submissions arrive by
    webhook."""
    assert {"LEAD_GENERATION", "QUALITY_LEAD"} == LEAD_GOALS
    assert {goal for goal in OUTCOMES if counts_leads(goal)} == LEAD_GOALS


def test_the_two_goals_bought_to_be_seen_answer_the_same_way() -> None:
    """Reach counts people and cannot be added across days or ad sets - the
    same person reached twice is one of them - so the only additive answer
    to "how much was this seen" is impressions, and both goals give it. One
    kind, therefore one word on the screen."""
    assert outcome_of("REACH") == outcome_of("IMPRESSIONS") == "view"


def test_a_conversation_and_a_call_stay_different_kinds() -> None:
    """They arrive in the same array and are the same integer to the fact
    table, and they are different things to whoever reads the screen.
    «Suhbat narxi» over a count of telephone calls is the silent mistake
    the kinds exist to prevent."""
    assert outcome_of("CONVERSATIONS") == "chat"
    assert outcome_of("QUALITY_CALL") == "call"


def test_the_traffic_goal_counts_a_departure_rather_than_a_lead() -> None:
    """Somebody leaving for the advertiser's own site is the result the
    campaign was bought for. It is not a lead - nothing arrives in this
    product's table - and it is not nothing either."""
    assert outcome_of("LANDING_PAGE_VIEWS") == "click"
    assert counts_leads("LANDING_PAGE_VIEWS") is False
    assert is_counted("LANDING_PAGE_VIEWS") is True


# --- The direction of the allowlist --------------------------------------
def test_a_goal_nobody_wrote_down_counts_nothing() -> None:
    """An allowlist, and the direction is the whole safety of it. A
    hand-built campaign in Ads Manager, a goal Meta adds next year, and an
    ad set the mirror has not synced yet all arrive here - and the other way
    round each of them would be judged on leads it may not produce."""
    for unknown in ("POST_ENGAGEMENT", "THRUPLAY", "SOMETHING_NEW", ""):
        assert outcome_of(unknown) == "none", unknown
        assert counts_leads(unknown) is False, unknown
        assert is_counted(unknown) is False, unknown


def test_the_goal_is_read_however_the_mirror_spelt_it() -> None:
    """The column is a mirror of a provider string, and a stored value with
    a stray space in it would otherwise fall through to "none" - which reads
    on the screen as a campaign whose result cannot be seen."""
    for spelling in ("conversations", " CONVERSATIONS ", "Conversations"):
        assert outcome_of(spelling) == "chat", spelling


# --- A lead on the owner's own website -----------------------------------
SITE_LEAD = {"pixel_id": "1", "custom_event_type": "LEAD"}


def test_a_website_goal_promoting_a_lead_is_a_site_lead() -> None:
    assert outcome_for("OFFSITE_CONVERSIONS", SITE_LEAD) == "site_lead"


def test_the_event_is_read_whatever_its_case() -> None:
    assert outcome_for("offsite_conversions", {"custom_event_type": "lead"}) == (
        "site_lead"
    )


@pytest.mark.parametrize(
    "promoted",
    [
        {"pixel_id": "1", "custom_event_type": "CONTACT"},
        {"pixel_id": "1", "custom_event_type": "COMPLETE_REGISTRATION"},
        {"pixel_id": "1", "custom_event_type": "PURCHASE"},
        {"pixel_id": "1"},
        None,
    ],
)
def test_every_other_website_event_stays_uncounted(
    promoted: dict[str, str] | None,
) -> None:
    """Only a lead reaches the provider's lead count; a contact or a
    registration on the same goal has nothing here to be counted in."""
    assert outcome_for("OFFSITE_CONVERSIONS", promoted) == "none"


def test_the_lead_event_on_another_goal_changes_nothing() -> None:
    assert outcome_for("LINK_CLICKS", SITE_LEAD) == "click"
    assert outcome_for("LEAD_GENERATION", SITE_LEAD) == "lead"


def test_a_site_lead_is_never_a_lead() -> None:
    """Nothing arrives by webhook for it. Read as a lead, every rule about
    leads that never reached this product would fire against an empty
    table - and the goal alone, which is what the agent's rules read, still
    says there is nothing to count."""
    assert not counts_leads("OFFSITE_CONVERSIONS")
    assert outcome_of("OFFSITE_CONVERSIONS") == "none"


# --- Which ad set speaks for a campaign ----------------------------------
def test_a_form_speaks_before_a_website_lead() -> None:
    assert campaign_goal(
        [
            ("a", "OFFSITE_CONVERSIONS", SITE_LEAD),
            ("b", "LEAD_GENERATION", None),
        ]
    ) == ("LEAD_GENERATION", None)


def test_a_website_lead_speaks_before_anything_else() -> None:
    assert campaign_goal(
        [("a", "LINK_CLICKS", None), ("b", "OFFSITE_CONVERSIONS", SITE_LEAD)]
    ) == ("OFFSITE_CONVERSIONS", SITE_LEAD)


def test_otherwise_the_first_by_id_speaks() -> None:
    assert campaign_goal(
        [("b", "CONVERSATIONS", None), ("a", "LINK_CLICKS", None)]
    ) == ("LINK_CLICKS", None)


def test_a_campaign_with_no_ad_set_has_no_goal() -> None:
    assert campaign_goal([]) == ("", None)
