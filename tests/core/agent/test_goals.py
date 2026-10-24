"""What the rules are allowed to say about a campaign that brings no leads.

Five goals have a result that is never a row in this product's lead table:
a website, a purchase, a conversation, a call, an ad bought to be seen.
Three of the agent's five rules divide by a lead, and
"spent money and brought in nobody" is true of all five goals on their best
week.

Three separate things are pinned here, and they are not variations of one:

* **What each rule is allowed to see.** A rule declaring ``needs_leads`` is
  handed an account with those ad sets removed - enforced by the scan
  rather than by a condition inside the rule, so a rule written next year
  cannot forget it.
* **What the cost rules measure against.** ``lead_totals``, not ``totals``.
  A website campaign beside a lead campaign adds spend to the division and
  nothing to the other side of it, which lifts every threshold in
  ``rules.money`` at once - including past the lead ad sets the waste rule
  exists to catch.
* **That the agent can undo what it did.** Without it the agent stops a
  call campaign and never offers it back, because every branch of ``_best``
  ranks candidates by a cost per lead they cannot have.

No database and no clock, like ``test_rules.py`` beside it.
"""

from typing import Any

from adskit import ProviderName

from core.agent import AccountFacts, AdSetFacts, Policy, scan
from core.agent.rules import (
    BROKEN_PICTURE,
    CODES,
    DORMANT,
    EXPENSIVE,
    IDLE,
    JUNK,
    NARROW_AUDIENCE,
    PROVIDER_ADVICE,
    PROVIDER_STOPPED,
    REFRESH_AD,
    REFUSED_AD,
    RULES,
    SATURATED,
    SITE_DOWN,
    STARVED,
    WASTING,
    WEAK_AD,
    WINNING,
)
from core.metrics import LEAD_GOALS, Totals, counts_leads

META = ProviderName("meta")
POLICY = Policy()

# The rules that price a result - each group against its own kind, and a
# kind nothing counts never judged. None of them needs leads any more.
PRICED = {WASTING, EXPENSIVE, WINNING}
# What has the same meaning whatever the campaign was selling. The last two
# are the ones whose subject is the provider: a deleted audience is deleted
# on a call campaign as on a form, and the platform's advice about who to
# show an advert to has nothing to do with what a lead costs.
ANY_GOAL = {
    STARVED,
    SATURATED,
    NARROW_AUDIENCE,
    WEAK_AD,
    # New words for an ignored advert: attention, which every goal has.
    REFRESH_AD,
    IDLE,
    PROVIDER_STOPPED,
    PROVIDER_ADVICE,
    # A picture the provider cannot show, or words it refused, stop a call
    # advert as they stop a form.
    BROKEN_PICTURE,
    REFUSED_AD,
    # A page that does not open stops a call advert's money as it stops a
    # form's.
    SITE_DOWN,
}


def _adset(**overrides: Any) -> AdSetFacts:
    figures = {
        "spend_minor": 100_000,
        "impressions": 10_000,
        "clicks": 300,
        "leads": 10,
        "qualified": 4,
    }
    figures.update(overrides.pop("totals", {}))
    return AdSetFacts(
        external_id=overrides.pop("external_id", "adset-1"),
        campaign_external_id=overrides.pop("campaign_external_id", "camp-1"),
        name=overrides.pop("name", "Qo'ng'iroq"),
        delivery=overrides.pop("delivery", "active"),
        totals=Totals(**figures),
        days_with_spend=overrides.pop("days_with_spend", 7),
        daily_budget_minor=overrides.pop("daily_budget_minor", 15_000),
        counts_leads=overrides.pop("counts_leads", False),
        # A campaign this product built, unless a test says otherwise. The
        # dataclass defaults the other way - the safe way - so a caller who
        # forgets loses a proposal rather than rewriting the audience of a
        # campaign somebody built in Ads Manager. See ``AdSetFacts.is_ours``.
        is_ours=overrides.pop("is_ours", True),
        **overrides,
    )


def _account(*adsets: AdSetFacts, **overrides: Any) -> AccountFacts:
    """An account whose two figures differ, which is the normal case now.

    ``totals`` is what was spent across everything; ``lead_totals`` is the
    part of it that could produce a lead. A test that passes neither gets a
    mixed account: a lead campaign at 10 000 a lead, and the same amount
    again spent somewhere no lead can happen.
    """
    return AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=overrides.pop(
            "totals", Totals(spend_minor=2_000_000, leads=100, qualified=40)
        ),
        lead_totals=overrides.pop(
            "lead_totals", Totals(spend_minor=1_000_000, leads=100, qualified=40)
        ),
        adsets=adsets,
    )


# --- The list itself -----------------------------------------------------
def test_only_a_form_on_the_ad_produces_a_lead_row_here() -> None:
    """Two goals, and both mean the same thing: a form the provider hosts,
    whose submissions arrive by webhook. Named rather than counted."""
    assert {"LEAD_GENERATION", "QUALITY_LEAD"} == LEAD_GOALS


def test_every_goal_this_product_now_builds_answers_correctly() -> None:
    """The five the product builds, and the one that stays closed."""
    assert counts_leads("LEAD_GENERATION") is True
    for goal in (
        "OFFSITE_CONVERSIONS",  # a purchase on the advertiser's own site
        "LINK_CLICKS",  # a visit
        "CONVERSATIONS",  # a thread we do not read
        "QUALITY_CALL",  # a telephone
        "AD_RECALL_LIFT",  # nothing of the kind
        "REACH",  # the store goal, if it is ever built
    ):
        assert counts_leads(goal) is False, goal


def test_a_goal_nobody_wrote_down_answers_no() -> None:
    """An allowlist, and the direction is the whole safety of it. A hand-built
    campaign in Ads Manager, a goal Meta adds next year, and an ad set the
    mirror has not synced yet all arrive here - and the other way round each
    of them would be judged on leads it may not be able to produce."""
    for unknown in ("POST_ENGAGEMENT", "THRUPLAY", "SOMETHING_NEW", ""):
        assert counts_leads(unknown) is False, unknown


# --- Which rule may see what ---------------------------------------------
def test_every_rule_declares_whether_it_needs_leads() -> None:
    """The declaration is required at registration, which is the whole
    mechanism: a rule added in the next block has to answer this before it
    can be in the table at all."""
    assert {rule.code for rule in RULES} == PRICED | ANY_GOAL
    assert {rule.code for rule in RULES if rule.needs_leads} == set()


def test_the_codes_are_derived_from_the_table_and_not_written_twice() -> None:
    assert set(CODES) == {rule.code for rule in RULES} | set(DORMANT)


def test_the_quality_rule_is_asleep_while_the_mark_is_off() -> None:
    """It divides by the owner's quality mark, which is switched off. Its
    code stays known - older rows carry it - and nothing new is found by it."""
    assert DORMANT == (JUNK,)
    assert JUNK not in {rule.code for rule in RULES}


def test_no_price_rule_fires_on_a_result_nothing_counts() -> None:
    """The matrix, stated as one assertion over every rule at once. An
    account of groups bought for something this product cannot count - a
    purchase on somebody else's website - produces nothing from the three
    rules that price a result, whatever thresholds they are given."""
    burning = _adset(totals={"leads": 0, "qualified": 0, "spend_minor": 900_000})
    proven = _adset(
        external_id="adset-2",
        totals={"leads": 0, "qualified": 0, "spend_minor": 150_000},
        daily_budget_minor=15_000,
    )

    found = scan(account=_account(burning, proven), policy=POLICY)

    assert [item.rule for item in found if item.rule in PRICED] == []


def test_the_same_ad_set_with_a_form_on_it_is_stopped() -> None:
    """The other half, and the reason the test above is about the goal
    rather than about the figures: nothing else changes."""
    burning = _adset(
        totals={"leads": 0, "qualified": 0, "spend_minor": 900_000},
        counts_leads=True,
    )

    found = scan(account=_account(burning), policy=POLICY)

    assert [item.rule for item in found] == [WASTING]


def test_a_starved_call_campaign_is_still_noticed() -> None:
    """Nothing here divides by a lead. An awareness campaign can run out of
    people to show an ad to exactly as a lead campaign can, and the money
    left unspent is the same money."""
    thin = _adset(
        totals={"leads": 0, "qualified": 0, "spend_minor": 20_000},
        daily_budget_minor=100_000,
        targeting={
            "geo_locations": {
                "custom_locations": [{"radius": 5, "distance_unit": "kilometer"}]
            }
        },
    )

    found = scan(account=_account(thin), policy=POLICY)

    assert [item.rule for item in found] == [STARVED]


# --- The benchmark -------------------------------------------------------
def test_a_campaign_that_cannot_bring_a_lead_does_not_price_one() -> None:
    """The distortion the split between the two totals exists to stop.

    Spend from a call campaign lands in the account total and never on the
    other side of the division, so the account's apparent cost per lead
    doubles - and the waste threshold is three times that figure. An ad set
    that genuinely burned 40 000 against real 10 000 leads stops being
    caught the day its owner starts a second kind of campaign: the limit
    moves from 30 000 to 60 000 and steps straight over it.
    """
    burning = _adset(
        totals={"leads": 0, "qualified": 0, "spend_minor": 40_000}, counts_leads=True
    )

    # The group's own 40 000 on top: it is measured against the others.
    honest = scan(
        account=_account(
            burning,
            lead_totals=Totals(spend_minor=1_040_000, leads=100, qualified=40),
        ),
        policy=POLICY,
    )
    polluted = scan(
        account=_account(
            burning,
            lead_totals=Totals(spend_minor=2_040_000, leads=100, qualified=40),
        ),
        policy=POLICY,
    )

    assert [item.rule for item in honest] == [WASTING]
    assert honest[0].evidence["account_cpl_minor"] == 10_000
    assert polluted == []


def test_the_benchmark_is_what_the_evidence_quotes() -> None:
    """The figure on the card and the figure the threshold was computed
    from are the same number. A card citing the account total while the
    rule fired on something else is a proposal nobody can check."""
    dear = _adset(
        totals={"leads": 6, "qualified": 0, "spend_minor": 120_000},
        counts_leads=True,
    )

    # The group's own six leads on top: it is measured against the others.
    found = scan(
        account=_account(
            dear, lead_totals=Totals(spend_minor=1_120_000, leads=106, qualified=40)
        ),
        policy=POLICY,
    )

    assert [item.rule for item in found] == [EXPENSIVE]
    assert found[0].evidence["account_cpl_minor"] == 10_000


def test_an_account_with_no_lead_campaign_at_all_has_no_benchmark() -> None:
    """Nothing to be dearer or cheaper *than*. Every cost rule returns
    empty rather than dividing by a total that includes only the campaigns
    it was told to ignore."""
    burning = _adset(totals={"leads": 0, "qualified": 0, "spend_minor": 900_000})

    found = scan(
        account=_account(burning, lead_totals=Totals()),
        policy=POLICY,
    )

    assert found == []


def test_the_account_total_is_left_alone() -> None:
    """Two questions, two fields. What the account spent is what the
    account spent - the explanation quotes it, and narrowing it would make
    the agent understate a week to somebody who paid for all of it."""
    account = _account(_adset())

    assert account.totals.spend_minor == 2_000_000
    assert account.lead_totals.spend_minor == 1_000_000


def test_narrowing_keeps_the_account_and_drops_only_the_ad_sets() -> None:
    call = _adset(external_id="call")
    form = _adset(external_id="form", counts_leads=True)

    narrowed = _account(call, form).only_lead_goals()

    assert [item.external_id for item in narrowed.adsets] == ["form"]
    assert narrowed.totals.spend_minor == 2_000_000
    assert narrowed.lead_totals.spend_minor == 1_000_000


# --- The agent can undo what it did --------------------------------------
def test_a_call_campaign_the_agent_stopped_is_offered_back() -> None:
    """Without this the agent stops one of these and never proposes
    starting it again: every branch of the choice ranks candidates by a
    cost per lead they cannot have, and falls through to nothing. That
    makes it the one object in this product it can break one way only."""
    stopped = _adset(
        delivery="paused",
        stopped_by_agent=True,
        totals={"leads": 0, "qualified": 0, "spend_minor": 400_000},
    )

    found = scan(account=_account(stopped), policy=POLICY)

    assert [item.rule for item in found] == [IDLE]
    assert found[0].kind == "resume"


def test_the_busiest_of_several_stopped_call_ad_sets_wins() -> None:
    """Nothing to rank them by except what they were doing. The one that
    spent the most is the one that was actually running."""
    quiet = _adset(
        external_id="quiet",
        delivery="paused",
        stopped_by_agent=True,
        totals={"leads": 0, "qualified": 0, "spend_minor": 30_000},
    )
    busy = _adset(
        external_id="busy",
        delivery="paused",
        stopped_by_agent=True,
        totals={"leads": 0, "qualified": 0, "spend_minor": 400_000},
    )

    found = scan(account=_account(quiet, busy), policy=POLICY)

    assert [item.ref.id for item in found] == ["busy"]


def test_a_lead_ad_set_that_never_produced_one_is_still_not_restarted() -> None:
    """The reasoning kept exactly where it applies. An ad set that
    could have brought a lead and did not has not earned a restart, and the
    money it spent proving that is not an argument for spending more."""
    stopped = _adset(
        delivery="paused",
        stopped_by_agent=True,
        counts_leads=True,
        totals={"leads": 0, "qualified": 0, "spend_minor": 400_000},
    )

    found = scan(account=_account(stopped), policy=POLICY)

    assert found == []


def test_a_lead_ad_set_with_leads_still_wins_over_a_busier_call_one() -> None:
    """The three passes are ordered rather than merged. A proven ad set
    beats an unmeasurable one however much the second one spent."""
    proven = _adset(
        external_id="proven",
        delivery="paused",
        stopped_by_agent=True,
        counts_leads=True,
        totals={"leads": 20, "qualified": 8, "spend_minor": 80_000},
    )
    busy = _adset(
        external_id="busy",
        delivery="paused",
        stopped_by_agent=True,
        totals={"leads": 0, "qualified": 0, "spend_minor": 900_000},
    )

    found = scan(account=_account(proven, busy), policy=POLICY)

    assert [item.ref.id for item in found] == ["proven"]
