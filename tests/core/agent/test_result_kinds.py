"""One price for a lead, and no verdict from a mark that is switched off.

The usual price of a lead is quoted in three places - the rules' threshold,
the card's "odatda" and the model's account lines - and all three have to
be the same number. And the owner's quality mark is switched off, so no
proposal is ranked or described by it.
"""

from typing import Any

from adskit import ProviderName

from core.agent import (
    NOT_WORKED,
    WORKED,
    AccountFacts,
    AdSetFacts,
    Aftermath,
    Policy,
    Recent,
    assess,
    scan,
)
from core.agent.benchmark import benchmark, benchmarks, lead_cost
from core.agent.funnel import Funnel
from core.agent.rules import EXPENSIVE, IDLE, STARVED, WASTING, WINNING
from core.metrics import Totals
from tests.core.agent.pace import at_week_pace

META = ProviderName("meta")
POLICY = Policy()


def group(
    external_id: str,
    *,
    spend: int,
    leads: int = 0,
    reported: int | None = None,
    results: int = 0,
    outcome: Any = "lead",
    **extra: Any,
) -> AdSetFacts:
    """A group bought for one kind of result, shown and spending."""
    totals = Totals(
        spend_minor=spend,
        impressions=10_000,
        leads=leads,
        leads_reported=leads if reported is None else reported,
        results=results,
        qualified=extra.pop("qualified", 0),
    )
    extra.setdefault("recent", at_week_pace(totals))
    return AdSetFacts(
        external_id=external_id,
        campaign_external_id=extra.pop("campaign", f"camp-{external_id}"),
        name=external_id,
        delivery=extra.pop("delivery", "active"),
        totals=totals,
        days_with_spend=7,
        counts_leads=outcome == "lead",
        outcome=outcome,
        is_ours=True,
        funnel=Funnel(spend_minor=spend, impressions=10_000),
        **extra,
    )


def test_the_usual_lead_price_is_the_one_the_rules_measure_against() -> None:
    """Ours says 10 on one group, the provider's says 10 on the other. The
    rules count the provider's, the count Ads Manager prints."""
    ours = group("ours", spend=100_000, leads=10, reported=0)
    theirs = group("theirs", spend=100_000, leads=0, reported=10)
    lead_totals = Totals(
        spend_minor=200_000, leads=10, leads_reported=10, impressions=20_000
    )

    assert benchmark([ours, theirs]).cost_minor == lead_cost(lead_totals) == 20_000


def test_a_conversation_is_never_counted_as_a_lead() -> None:
    form = group("form", spend=50_000, leads=5)
    chat = group("chat", spend=70_000, results=35, outcome="chat")

    found = benchmarks([form, chat])

    assert found["lead"].results == 5
    assert found["chat"].results == 35
    assert found["chat"].cost_minor == 2_000


# --- the quality mark is switched off -------------------------------------
def stopped(external_id: str, **figures: Any) -> AdSetFacts:
    return group(
        external_id,
        campaign="camp-1",
        delivery="paused",
        stopped_by_agent=True,
        **figures,
    )


def account(*adsets: AdSetFacts) -> AccountFacts:
    totals = Totals(spend_minor=1_000_000, leads=100, leads_reported=100)
    return AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=totals,
        lead_totals=totals,
        adsets=adsets,
    )


def test_a_restart_goes_to_the_cheapest_lead_not_the_most_marked() -> None:
    """Marks made before the mark was switched off must not decide which
    group is started again."""
    marked = stopped("marked", spend=90_000, leads=6, qualified=6)
    cheap = stopped("cheap", spend=60_000, leads=10, qualified=0)

    [found] = [
        item
        for item in scan(account=account(marked, cheap), policy=POLICY)
        if item.rule == IDLE
    ]

    assert found.ref.id == "cheap"


def test_a_restart_card_says_nothing_about_quality() -> None:
    only = stopped("only", spend=60_000, leads=10, qualified=4)

    [found] = scan(account=account(only), policy=POLICY)

    assert "qualified" not in found.evidence
    assert "cpql_minor" not in found.evidence
    assert found.evidence["leads"] == 10
    assert found.evidence["cpl_minor"] == 6_000


# --- the price rules judge every kind of result ---------------------------
def chat(external_id: str, *, spend: int, results: int, **extra: Any) -> AdSetFacts:
    return group(external_id, spend=spend, results=results, outcome="chat", **extra)


def test_a_chat_group_burning_money_with_no_conversation_is_stopped() -> None:
    """What a conversation usually costs is read over the other chat groups -
    20 000 for twenty, 1 000 each. A group that spent 90 000 on none is
    money gone; it used to be invisible, because the rule counted leads."""
    working = chat("working", spend=20_000, results=20)
    burning = chat("burning", spend=90_000, results=0)

    found = [item for item in scan(account=account(working, burning), policy=POLICY)]

    [stop] = [item for item in found if item.rule == WASTING]
    assert stop.ref.id == "burning"
    assert stop.evidence["outcome"] == "chat"
    assert stop.evidence["results"] == 0
    assert stop.evidence["account_cost_minor"] == 1_000


def test_a_dear_chat_group_gets_less_money_by_its_conversation_price() -> None:
    cheap = chat("cheap", spend=20_000, results=40, daily_budget_minor=5_000)
    dear = chat(
        "dear",
        spend=60_000,
        results=10,
        daily_budget_minor=10_000,
        recent=Recent(days=3, totals=Totals(spend_minor=18_000, results=3)),
    )

    found = scan(account=account(cheap, dear), policy=POLICY)

    [lower] = [item for item in found if item.rule == EXPENSIVE]
    assert lower.ref.id == "dear"
    assert lower.evidence["cost_minor"] == 6_000


def test_a_cheap_chat_group_held_back_by_its_budget_gets_more() -> None:
    dear = chat("dear", spend=60_000, results=10, daily_budget_minor=20_000)
    cheap = chat("cheap", spend=35_000, results=35, daily_budget_minor=5_000)

    found = scan(account=account(dear, cheap), policy=POLICY)

    [raise_] = [item for item in found if item.rule == WINNING]
    assert raise_.ref.id == "cheap"
    assert raise_.evidence["outcome"] == "chat"


def test_a_group_whose_budget_just_moved_is_not_called_held_back() -> None:
    """Its allowance is today's budget times the days, which ran on another
    one. A raise on the strength of that share is a raise on arithmetic."""
    dear = chat("dear", spend=60_000, results=10, daily_budget_minor=20_000)
    cheap = chat(
        "cheap", spend=35_000, results=35, daily_budget_minor=5_000, budget_moved=True
    )

    found = scan(account=account(dear, cheap), policy=POLICY)

    assert WINNING not in [item.rule for item in found]


def test_a_group_whose_budget_just_moved_is_not_called_starved() -> None:
    starving = group(
        "starving",
        spend=10_000,
        leads=5,
        daily_budget_minor=15_000,
        targeting={"age_min": 25, "age_max": 45},
    )

    assert STARVED in [
        item.rule for item in scan(account=account(starving), policy=POLICY)
    ]
    moved = group(
        "starving",
        spend=10_000,
        leads=5,
        daily_budget_minor=15_000,
        targeting={"age_min": 25, "age_max": 45},
        budget_moved=True,
    )
    assert STARVED not in [
        item.rule for item in scan(account=account(moved), policy=POLICY)
    ]


# --- and each is graded on its own kind -----------------------------------
def test_less_money_on_a_chat_group_is_graded_on_the_conversation_price() -> None:
    """The lead grading would find no lead after it and call it failed."""
    evidence = {"days": 7, "outcome": "chat", "results": 10, "cost_minor": 6_000}
    after = Aftermath(
        totals=Totals(spend_minor=30_000, results=10, impressions=5_000), days=5
    )

    verdict = assess(rule=EXPENSIVE, evidence=evidence, after=after, min_days=3)

    assert verdict is not None
    assert verdict.outcome == WORKED


def test_more_money_on_a_chat_group_is_graded_on_more_conversations() -> None:
    evidence = {"days": 7, "outcome": "chat", "results": 14, "cost_minor": 1_000}
    fewer = Aftermath(totals=Totals(spend_minor=20_000, results=5), days=5)
    more = Aftermath(totals=Totals(spend_minor=20_000, results=25), days=5)

    worse = assess(rule=WINNING, evidence=evidence, after=fewer, min_days=3)
    better = assess(rule=WINNING, evidence=evidence, after=more, min_days=3)
    assert worse is not None and worse.outcome == NOT_WORKED
    assert better is not None and better.outcome == WORKED
