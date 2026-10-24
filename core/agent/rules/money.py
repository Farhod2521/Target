"""Rules about what an ad set costs, in the result it was bought for.

Three of the five, and all three compare against the account's own history
rather than against a figure written into this file. A cost per lead has no
universal good value - a barbershop's and a clinic's differ by an order of
magnitude - so "expensive" can only ever mean *dearer than this owner
normally pays*, and an account with no lead yet has no benchmark and
therefore gets no proposals from here. "Normally" is the account's other
groups: a group is never measured against a sum it is part of.

**A lead, not a qualified lead.** The owner's quality mark is switched off,
so a price per qualified lead has no source and a rule built on it never
fires. Leads are counted the larger way, ours or the provider's - see
:func:`core.agent.benchmark.lead_cost` - so a lost webhook does not make a
working group look dear and take its money away.

**The benchmark is ``lead_totals``, not ``totals``.** They differ the
moment an account runs anything besides a lead form: a website campaign
and a call campaign add spend to the division and nothing to the other
side of it, so one of each beside one lead campaign makes a lead here look
twice as dear as it is. Every threshold below is a multiple of that
figure, which means the error does not stay in one rule - it lifts the
waste threshold past the ad sets it was written to catch, and makes every
remaining lead ad set look cheap enough to deserve more money.

**Every kind of result, each against its own kind.** A chat group is
judged by what a conversation costs against the account's other chat
groups, a call group by its calls, a website group by its visits - the
family benchmark :func:`core.agent.benchmark.benchmarks` keeps. A lead
group keeps the lead benchmark above. Nought is only a failure for a group
whose result *can* be counted: a group bought for a purchase on somebody
else's website has no count here, and it is never judged by these rules.
"""

from dataclasses import dataclass

from adskit import ExternalRef

from core.agent.benchmark import (
    family_of,
    lead_count,
    peers,
    peers_lead_cost,
    per_of,
    result_cost,
    result_count,
)
from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, judgeable

# Stable codes, stored on every suggestion. The Django layer maps them to
# Uzbek and the approval path re-runs them by name, so renaming one is a
# migration rather than a rename.
WASTING = "wasting"
WINNING = "winning"
EXPENSIVE = "expensive"

# How many results before a price is treated as a price rather than as luck.
# On two or three, one lucky or unlucky day is the whole difference, and
# money moved on it is money moved on noise.
MIN_RESULTS_FOR_A_PRICE = 5
# So much dearer that fewer results already say it: three times the usual
# price on even one result is not a bad day.
FAR_DEARER_PCT = 300


@dataclass(frozen=True, slots=True)
class _Priced:
    """One group's result against what that result usually costs here.

    ``usual`` is the price of ``per`` results - one, or a thousand showings.
    """

    family: str
    count: int
    usual: int
    per: int

    def cost_of(self, spend_minor: int) -> int | None:
        return result_cost(
            spend_minor=spend_minor, count=self.count, family=self.family
        )


def _priced(item: AdSetFacts, *, account: AccountFacts) -> _Priced | None:
    """The group's count and the usual price of its kind, or ``None``.

    The usual price is the account's *other* groups of the same kind - see
    :func:`core.agent.benchmark.peers`. ``None`` for a kind nothing counts
    and for an account with no other price for it - no benchmark, no such
    thing as dearer than usual. A group's own history is the launch
    watch's to compare.
    """
    family = family_of(item)
    usual: int | None
    if family == "lead":
        usual = peers_lead_cost(account.lead_totals, item)
        count: int | None = lead_count(item)
    else:
        usual = peers(account.adsets, item).cost_minor
        count = result_count(item)
    if usual is None or count is None:
        return None
    return _Priced(family=family, count=count, usual=int(usual), per=per_of(family))


def wasting(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Spent real money and produced no result at all - stop it.

    Zero results of the kind it was bought for - no form filled in, no
    conversation, no call, no visit. Zero leads, not zero *qualified*
    leads: an ad set bringing in people the owner keeps rejecting is a
    targeting problem and is somebody else's rule; this one is for the ad
    set nobody ever answered, which is the only case where the money is
    unambiguously gone.

    **Zero by both counts, ours and the provider's.** A group whose leads
    stopped reaching this product - a lost subscription, a sweep that could
    not read the form - has nought in our table and a working form at the
    provider, and stopping it would stop the one thing that is working. The
    larger count is the one the diagnosis reads too, see
    :func:`core.agent.benchmark.lead_count`.

    "Nobody filled a form" is only a fact about an ad set that has a form.
    A call campaign produces nought leads on its best week; what it is
    judged by is its calls, against what a call costs this account.

    The threshold is a multiple of what one result normally costs this
    account. Below it there is nothing to conclude: an account whose leads
    cost 50 000 has learned nothing from an ad set that has spent 30 000.
    """
    found: list[Finding] = []
    for item in account.adsets:
        priced = _priced(item, account=account)
        if priced is None or not judgeable(item, policy) or priced.count != 0:
            continue
        spend = item.totals.spend_minor
        if spend * priced.per < priced.usual * policy.waste_multiple:
            continue
        found.append(
            Finding(
                kind="pause",
                rule=WASTING,
                ref=_ref(account, item),
                weight=spend,
                evidence={
                    "days": item.days_with_spend,
                    "spend_minor": spend,
                    "impressions": item.totals.impressions,
                    # Zero, always, or this rule would not have fired. On
                    # the card anyway: it is the line the whole proposal
                    # rests on, and a figure inferred from a rule's name is
                    # a figure the reader has to take on trust.
                    **_result_evidence(item, priced),
                    "multiple": policy.waste_multiple,
                    "currency": account.currency,
                },
            )
        )
    return found


def winning(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Cheap, proven, and held back by its own budget - give it more.

    Three conditions, and the third is the one that is usually missing from
    advice like this. An ad set below its budget does not want money: it
    already has money it cannot spend, and raising the figure changes a
    number in an interface and nothing in the account. Only an ad set
    pressed against its allowance converts more budget into more leads.
    """
    found: list[Finding] = []
    for item in account.adsets:
        budget = item.daily_budget_minor
        priced = _priced(item, account=account)
        if priced is None or not judgeable(item, policy) or not budget:
            continue
        if item.learning_limited:
            # Too few results a week to be a price; its own note says so.
            continue
        if priced.count < MIN_RESULTS_FOR_A_PRICE:
            continue
        spend = item.totals.spend_minor
        if (
            spend * priced.per * 100
            > priced.usual * priced.count * policy.win_share_pct
        ):
            continue
        # How much of its allowance it used is read against today's
        # budget; a budget moved inside the window makes that a different
        # group's allowance, and "held back by its budget" cannot be said.
        if item.budget_moved or item.spend_share < policy.constrained_share_pct:
            continue

        raised = _stepped(budget, policy.budget_step_pct)
        found.append(
            Finding(
                kind="increase_budget",
                rule=WINNING,
                ref=_ref(account, item),
                weight=(raised - budget) * account.window_days,
                evidence=_cost_evidence(account, item, priced)
                | {"from_minor": budget, "to_minor": raised},
                payload={"daily_budget_minor": raised},
            )
        )

    return found


def expensive(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Leads far dearer than this account normally pays - spend less on it.

    Not a stop. This ad set does produce leads, and switching it off would
    lose them; it is buying them at a price the same account beats
    elsewhere, so the answer is less money rather than none.

    "Far dearer" is ``Policy.lose_share_pct`` of the account's own cost per
    lead - the line the diagnosis also calls poor results at - on at least
    :data:`MIN_RESULTS_FOR_A_PRICE` results; on fewer, only at
    :data:`FAR_DEARER_PCT`. Only judged once the provider has finished
    learning: ``judgeable`` refuses a learning group, whose early price is
    the provider still searching.

    Refuses to propose a figure under the provider's floor. A budget below
    it is rejected on arrival, and a proposal that cannot be carried out is
    worse than no proposal - it puts a button on a screen that fails when
    pressed.
    """
    found: list[Finding] = []
    for item in account.adsets:
        budget = item.daily_budget_minor
        priced = _priced(item, account=account)
        if priced is None or not judgeable(item, policy) or not budget:
            continue
        if item.learning_limited:
            # Too few results a week to be a price; its own note says so.
            continue
        count = priced.count
        if count < 1:
            continue
        spend = item.totals.spend_minor
        bar = (
            policy.lose_share_pct
            if count >= MIN_RESULTS_FOR_A_PRICE
            else FAR_DEARER_PCT
        )
        if spend * priced.per * 100 < priced.usual * count * bar:
            continue

        lowered = _stepped(budget, -policy.budget_step_pct)
        if item.floor_minor > 0 and lowered < item.floor_minor:
            continue

        found.append(
            Finding(
                kind="decrease_budget",
                rule=EXPENSIVE,
                ref=_ref(account, item),
                weight=max(0, spend - count * priced.usual // priced.per),
                evidence=_cost_evidence(account, item, priced)
                | {"from_minor": budget, "to_minor": lowered},
                payload={"daily_budget_minor": lowered},
            )
        )

    return found


def _cost_evidence(
    account: AccountFacts, item: AdSetFacts, priced: _Priced
) -> dict[str, object]:
    """The numbers both budget rules show their working with."""
    return {
        "days": item.days_with_spend,
        "spend_minor": item.totals.spend_minor,
        **_result_evidence(item, priced),
        "spend_share": item.spend_share,
        "currency": account.currency,
    }


def _result_evidence(item: AdSetFacts, priced: _Priced) -> dict[str, object]:
    """The group's result and its price, in the words of its own kind.

    A lead group's keep the lead keys every card and every grading already
    reads. Any other kind carries what it was bought for, how many came,
    what one cost and what one usually costs - the keys the card's result
    line and the result-price grading read, so a conversation is shown and
    judged as a conversation.
    """
    cost = priced.cost_of(item.totals.spend_minor)
    if priced.family == "lead":
        return {
            "leads": priced.count,
            "cpl_minor": int(cost) if cost is not None else None,
            "account_cpl_minor": priced.usual,
        }
    return {
        "outcome": priced.family,
        "results": priced.count,
        "cost_minor": cost,
        "account_cost_minor": priced.usual,
    }


def _stepped(budget_minor: int, percent: int) -> int:
    """A budget moved by a percentage, still a whole number of minor units.

    Rounded rather than truncated, and never returned as zero: a budget of
    zero is not a smaller budget, it is a stopped ad set arrived at through
    the wrong door.
    """
    return max(1, round(budget_minor * (100 + percent) / 100))


def _ref(account: AccountFacts, item: AdSetFacts) -> ExternalRef:
    return ExternalRef(provider=account.provider, level="adset", id=item.external_id)


__all__ = [
    "EXPENSIVE",
    "FAR_DEARER_PCT",
    "MIN_RESULTS_FOR_A_PRICE",
    "WASTING",
    "WINNING",
    "expensive",
    "wasting",
    "winning",
]
