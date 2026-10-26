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
    count_in,
    family_of,
    last_days_level,
    peers,
    peers_lead_cost,
    per_of,
    result_cost,
    result_count,
)
from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, judgeable
from core.agent.sufficiency import SPEND_MULTIPLE, enough_spent
from core.agent.usual import PriceLevel
from core.metrics import heard_leads

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

    The usual price is the one :attr:`core.agent.benchmark.Benchmark.cost_minor`
    names: the pair's own fortnight, and the account's *other* groups of the
    kind only where the fortnight has no middle. ``None`` for a kind nothing
    counts and where neither has a price - no such thing as dearer than
    usual.
    """
    family = family_of(item)
    count = result_count(item)
    own = account.usual.get(family)
    usual = own.cost_minor if own is not None else None
    if usual is None:
        usual = (
            peers_lead_cost(account.lead_totals, item)
            if family == "lead"
            else peers(account.adsets, item).cost_minor
        )
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
    provider, and stopping it would stop the one thing that is working; a
    lead the provider has not counted yet is the same in reverse. See
    :func:`core.metrics.heard_leads`.

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
        if heard_leads(ours=item.totals.leads, reported=item.totals.leads_reported):
            continue
        spend = item.totals.spend_minor
        if not enough_spent(
            spend_minor=spend, usual_cost_minor=priced.usual, per=priced.per
        ):
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
                    "multiple": SPEND_MULTIPLE,
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
        # The brief changes no budget before three results' usual price is
        # spent, however cheap the few results so far came.
        if not enough_spent(
            spend_minor=spend, usual_cost_minor=priced.usual, per=priced.per
        ):
            continue
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
    """Results far dearer than this pair usually pays - spend less on it.

    Not a stop. This ad set does produce results, and switching it off
    would lose them; it is buying them at a price the same advertising
    beats on most days, so the answer is less money rather than none.

    "Far dearer" is the brief's one reading of it: the last three finished
    days past twice the fortnight's median day, on three results' usual
    price spent - see :func:`core.agent.usual.price_level`. The night's
    diagnosis and the watch's message ask the same question, so a group
    called dear here is called dear everywhere. Only judged once the
    provider has finished learning: ``judgeable`` refuses a learning group,
    whose early price is the provider still searching.

    Refuses to propose a figure under the provider's floor. A budget below
    it is rejected on arrival, and a proposal that cannot be carried out is
    worse than no proposal - it puts a button on a screen that fails when
    pressed.
    """
    found: list[Finding] = []
    for item in account.adsets:
        budget = item.daily_budget_minor
        if not judgeable(item, policy) or not budget or item.learning_limited:
            continue
        last = _last_days(item, account=account)
        if last is None or last.level != "act" or last.count < 1:
            continue
        lowered = _stepped(budget, -policy.budget_step_pct)
        if item.floor_minor > 0 and lowered < item.floor_minor:
            continue
        spend = item.recent.totals.spend_minor
        found.append(
            Finding(
                kind="decrease_budget",
                rule=EXPENSIVE,
                ref=_ref(account, item),
                weight=max(0, spend - last.count * last.usual // last.per),
                evidence=_last_evidence(account, item, last)
                | {"from_minor": budget, "to_minor": lowered},
                payload={"daily_budget_minor": lowered},
            )
        )

    return found


@dataclass(frozen=True, slots=True)
class _Last:
    """The last three days' result against the fortnight's median price."""

    family: str
    count: int
    usual: int
    per: int
    level: PriceLevel | None


def _last_days(item: AdSetFacts, *, account: AccountFacts) -> _Last | None:
    """The group's last days as the brief reads a price, or ``None``.

    Against the usual price :func:`_priced` names - the one the card and
    the night's diagnosis quote. ``None`` for a kind nothing counts and
    where nothing has a usual price.
    """
    priced = _priced(item, account=account)
    if priced is None:
        return None
    recent = item.recent
    count = count_in(
        totals=recent.totals, link_clicks=recent.link_clicks, family=priced.family
    )
    if count is None:
        return None
    level = last_days_level(item, usual_cost_minor=priced.usual)
    return _Last(
        family=priced.family,
        count=count,
        usual=priced.usual,
        per=priced.per,
        level=level,
    )


def _last_evidence(
    account: AccountFacts, item: AdSetFacts, last: _Last
) -> dict[str, object]:
    """The numbers the budget-down card shows its working with: the days
    the price was read over, not the week."""
    spend = item.recent.totals.spend_minor
    cost = result_cost(spend_minor=spend, count=last.count, family=last.family)
    evidence: dict[str, object] = {
        "days": item.recent.days,
        "spend_minor": spend,
        "spend_share": item.spend_share,
        "currency": account.currency,
    }
    if last.family == "lead":
        return evidence | {
            "leads": last.count,
            "cpl_minor": int(cost) if cost is not None else None,
            "account_cpl_minor": last.usual,
        }
    return evidence | {
        "outcome": last.family,
        "results": last.count,
        "cost_minor": cost,
        "account_cost_minor": last.usual,
    }


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
    "MIN_RESULTS_FOR_A_PRICE",
    "WASTING",
    "WINNING",
    "expensive",
    "wasting",
    "winning",
]
