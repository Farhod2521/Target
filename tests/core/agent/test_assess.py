"""core/agent/assess: whether a change did what its rule expected.

No database and no clock, like the rules the verdicts answer to. The
aftermath arrives as values, which is what lets every boundary - too few
days, a price that held, an absence that proves a stop - be argued here.
"""

from collections.abc import Mapping
from typing import Any

from core.agent import (
    EXPECTATIONS,
    JUDGED_ON_PARENT,
    NOT_WORKED,
    UNCLEAR,
    WORKED,
    Aftermath,
    assess,
)
from core.agent.rules import (
    BROKEN_PICTURE,
    CODES,
    EXPENSIVE,
    IDLE,
    JUNK,
    NARROW_AUDIENCE,
    REFRESH_AD,
    REFUSED_AD,
    SATURATED,
    STARVED,
    WASTING,
    WEAK_AD,
    WINNING,
)
from core.metrics import Totals

MIN_DAYS = 3


def _assess(
    rule: str,
    evidence: Mapping[str, Any],
    after: Totals,
    days: int,
    link_clicks: int = 0,
) -> Any:
    return assess(
        rule=rule,
        evidence=evidence,
        after=Aftermath(totals=after, link_clicks=link_clicks, days=days),
        min_days=MIN_DAYS,
    )


def test_every_rule_promises_something() -> None:
    assert set(EXPECTATIONS) == set(CODES)


# --- a pause is proved by absence ----------------------------------------
def test_no_spend_after_a_pause_is_the_success_it_predicted() -> None:
    """A paused ad set produces no figures at all, so nought days is the
    answer here - not a question."""
    verdict = _assess(WASTING, {"days": 5}, Totals(), 0)

    assert verdict is not None
    assert verdict.outcome == WORKED
    assert verdict.figures["expected"] == "spend_stops"


def test_spend_continuing_after_a_pause_did_not_work() -> None:
    verdict = _assess(WASTING, {"days": 5}, Totals(spend_minor=12_000), 2)

    assert verdict is not None
    assert verdict.outcome == NOT_WORKED


# --- a resume is proved only by presence ----------------------------------
def test_spend_returning_proves_the_resume() -> None:
    verdict = _assess(IDLE, {}, Totals(spend_minor=8_000), 1)

    assert verdict is not None
    assert verdict.outcome == WORKED


def test_silence_after_a_resume_stays_unanswered() -> None:
    """Not delivering yet, or a sync that has not caught up - absence
    cannot tell the two apart, so it never becomes a verdict."""
    assert _assess(IDLE, {}, Totals(), 0) is None


# --- more budget must buy more leads at no worse a price ------------------
WINNING_BEFORE = {"leads": 2, "days": 7, "cpl_minor": 50_000}


def test_a_raise_that_lifted_the_rate_at_a_held_price_worked() -> None:
    after = Totals(spend_minor=30_000, leads=6, leads_reported=6)

    verdict = _assess(WINNING, WINNING_BEFORE, after, 3)

    assert verdict is not None
    assert verdict.outcome == WORKED


def test_a_raise_that_bought_dear_leads_did_not_work() -> None:
    """The count rose and the price broke its bound - money moved, not
    results."""
    after = Totals(spend_minor=180_000, leads=3, leads_reported=3)

    verdict = _assess(WINNING, WINNING_BEFORE, after, 3)

    assert verdict is not None
    assert verdict.outcome == NOT_WORKED


def test_a_raise_with_a_falling_rate_did_not_work() -> None:
    after = Totals(spend_minor=10_000, leads=0, leads_reported=0)

    verdict = _assess(WINNING, WINNING_BEFORE, after, 3)

    assert verdict is not None
    assert verdict.outcome == NOT_WORKED


def test_too_few_days_is_not_a_verdict() -> None:
    """A verdict needs as many days as an opinion did."""
    after = Totals(spend_minor=30_000, leads=6, leads_reported=6)

    assert _assess(WINNING, WINNING_BEFORE, after, MIN_DAYS - 1) is None


def test_evidence_an_older_rule_wrote_reads_as_unclear() -> None:
    """A guessed nought would produce a confident verdict from no data."""
    verdict = _assess(WINNING, {}, Totals(leads=5, leads_reported=5), 3)

    assert verdict is not None
    assert verdict.outcome == UNCLEAR


# --- less budget must mean cheaper leads, still arriving ------------------
def test_a_cut_that_lowered_the_price_worked() -> None:
    after = Totals(spend_minor=40_000, leads=2, leads_reported=2)

    verdict = _assess(EXPENSIVE, {"cpl_minor": 50_000}, after, 3)

    assert verdict is not None
    assert verdict.outcome == WORKED


def test_a_cut_after_which_no_lead_arrived_did_not_work() -> None:
    """Not a cheaper campaign - a stopped one arrived at slowly."""
    after = Totals(spend_minor=40_000, leads=0, leads_reported=0)

    verdict = _assess(EXPENSIVE, {"cpl_minor": 50_000}, after, 3)

    assert verdict is not None
    assert verdict.outcome == NOT_WORKED


# --- a wider audience must let the ad set spend ---------------------------
def test_delivery_opening_up_proves_the_widening() -> None:
    before = {"spend_minor": 30_000, "days": 6}

    verdict = _assess(STARVED, before, Totals(spend_minor=24_000), 3)

    assert verdict is not None
    assert verdict.outcome == WORKED


def test_delivery_still_pinched_did_not_work() -> None:
    before = {"spend_minor": 30_000, "days": 6}

    verdict = _assess(STARVED, before, Totals(spend_minor=12_000), 3)

    assert verdict is not None
    assert verdict.outcome == NOT_WORKED


# --- history meeting newer code -------------------------------------------
def test_a_retired_rule_reads_as_unclear_not_a_crash() -> None:
    verdict = _assess("some_old_rule", {"days": 5}, Totals(), 2)

    assert verdict is not None
    assert verdict.outcome == UNCLEAR


def test_a_junked_ad_set_is_graded_like_any_other_stop() -> None:
    """Two rules, one promise. Both end in a pause, and a pause is proved
    the same way whichever argument produced it."""
    verdict = _assess(JUNK, {"days": 5, "leads": 12}, Totals(), 0)

    assert verdict is not None
    assert verdict.outcome == WORKED
    assert verdict.figures["expected"] == "spend_stops"


def test_a_widened_audience_that_clicks_again_worked() -> None:
    after = Totals(spend_minor=40_000, impressions=20_000)

    verdict = _assess(SATURATED, {"late_ctr_bp": 80}, after, 4, link_clicks=300)

    assert verdict is not None
    assert verdict.outcome == WORKED
    assert verdict.figures["link_clicks"] == 300


def test_a_widened_audience_still_not_clicking_did_not_work() -> None:
    after = Totals(spend_minor=40_000, impressions=20_000)

    verdict = _assess(SATURATED, {"late_ctr_bp": 200}, after, 4, link_clicks=100)

    assert verdict is not None
    assert verdict.outcome == NOT_WORKED


def test_the_widening_is_graded_against_the_worn_half_not_the_fresh_one() -> None:
    """Beating the early half was never the promise: some of that fall is
    the ad ageing, and no audience change reverses it."""
    after = Totals(spend_minor=40_000, impressions=20_000)
    evidence = {"early_ctr_bp": 400, "late_ctr_bp": 100}

    verdict = _assess(SATURATED, evidence, after, 4, link_clicks=300)

    assert verdict is not None
    assert verdict.outcome == WORKED


def test_a_narrowing_that_lowered_the_reported_price_worked() -> None:
    before = {"spend_minor": 300_000, "leads_reported": 10}
    after = Totals(spend_minor=90_000, leads_reported=6)

    verdict = _assess(NARROW_AUDIENCE, before, after, 4)

    assert verdict is not None
    assert verdict.outcome == WORKED


def test_a_narrowing_with_no_leads_after_it_did_not_work() -> None:
    before = {"spend_minor": 300_000, "leads_reported": 10}
    after = Totals(spend_minor=90_000, leads_reported=0)

    verdict = _assess(NARROW_AUDIENCE, before, after, 4)

    assert verdict is not None
    assert verdict.outcome == NOT_WORKED


# --- switching off an advert is graded on the group it sat in ------------
GROUP_BEFORE: Mapping[str, Any] = {
    "days": 7,
    "adset_spend_minor": 160_000,
    "adset_leads_reported": 20,
}


def test_the_advert_rule_is_the_one_judged_on_its_parent() -> None:
    """Stated as a set rather than as a condition in a service, so the
    question "whose figures answer this promise" has one answer in the
    domain - see ``apps.agent.services.assess_outcomes``."""
    assert set(JUDGED_ON_PARENT) == {WEAK_AD, REFRESH_AD, BROKEN_PICTURE, REFUSED_AD}


def test_a_replaced_picture_worked_once_the_group_spends_again() -> None:
    """A new advert with a new id: the group is the only thing whose figures
    continue, and spending again is what the fix promised."""
    worked = _assess(BROKEN_PICTURE, {}, Totals(spend_minor=4_000), 1)
    silent = _assess(BROKEN_PICTURE, {}, Totals(), 0)

    assert worked is not None
    assert worked.outcome == WORKED
    assert silent is None


def test_the_group_buying_leads_cheaper_is_the_success() -> None:
    """The same budget, now going only to the adverts that work. 8 000 a
    lead against the 8 000 before it would not be an improvement; 6 000 is."""
    verdict = _assess(
        WEAK_AD,
        GROUP_BEFORE,
        Totals(spend_minor=120_000, leads_reported=20),
        5,
    )

    assert verdict is not None
    assert verdict.outcome == WORKED


def test_the_group_paying_more_per_lead_is_a_failure() -> None:
    verdict = _assess(
        WEAK_AD,
        GROUP_BEFORE,
        Totals(spend_minor=200_000, leads_reported=15),
        5,
    )

    assert verdict is not None
    assert verdict.outcome == NOT_WORKED


def test_a_group_that_stopped_spending_altogether_is_unclear() -> None:
    """Something else happened to it - the owner paused it, its campaign
    ended - and dividing by an empty aftermath would report that as this
    change having gone wrong."""
    verdict = _assess(WEAK_AD, GROUP_BEFORE, Totals(), 5)

    assert verdict is not None
    assert verdict.outcome == UNCLEAR


def test_a_row_with_no_parent_figures_is_unclear_rather_than_failed() -> None:
    """Evidence written by an older version of the rule is a real thing to
    meet, and a comparison against a guessed nought would produce a
    confident verdict from no data."""
    verdict = _assess(
        WEAK_AD, {"days": 7}, Totals(spend_minor=120_000, leads_reported=20), 5
    )

    assert verdict is not None
    assert verdict.outcome == UNCLEAR


def test_too_few_days_is_still_too_early_to_say() -> None:
    assert (
        _assess(WEAK_AD, GROUP_BEFORE, Totals(spend_minor=50_000, leads_reported=9), 1)
        is None
    )
