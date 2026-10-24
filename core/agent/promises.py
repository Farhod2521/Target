"""What each change promised, and how that promise is tested.

:mod:`core.agent.assess` holds the argument; this module holds the answers
to "did it?" - one per rule, and two of the eleven rules share a promise
with a neighbour rather than inventing one of their own.

**A rule is judged on the figure it was triggered by.** Triggering on one
measure and grading on a neighbouring one is how a rule quietly acquires a
pass mark it never earned.

Everything compares per-day rates rather than window totals, because the
two windows are never the same length: the evidence summed a week, the
aftermath sums however many full days have passed since the change.
"""

from collections.abc import Mapping
from typing import Any, Final, Protocol

from core.agent.benchmark import count_in, lead_cost, result_cost
from core.agent.contracts import Aftermath, Verdict
from core.agent.facts import ctr_bp
from core.agent.rules import (
    BROKEN_PICTURE,
    EXPENSIVE,
    IDLE,
    JUNK,
    NARROW_AUDIENCE,
    PROVIDER_ADVICE,
    PROVIDER_STOPPED,
    REFRESH_AD,
    REFUSED_AD,
    SATURATED,
    SITE_DOWN,
    STARVED,
    WASTING,
    WEAK_AD,
    WINNING,
)

# How a change turned out. Codes, never sentences - the Django layer maps
# them to Uzbek, the same bargain every domain word here makes.
#
# ``GONE`` is never returned by :func:`core.agent.assess`: an object that no
# longer exists is a fact about the mirror, and the mirror is the caller's
# to read. The code lives here so the vocabulary has one home.
WORKED: Final = "worked"
NOT_WORKED: Final = "not_worked"
UNCLEAR: Final = "unclear"
GONE: Final = "gone"

# What each rule's change promises, by rule code. The screen's "what we
# expect" line and the assessment's question are both this table, which is
# what keeps them the same sentence.
EXPECTATIONS: Final[dict[str, str]] = {
    WASTING: "spend_stops",
    WINNING: "more_leads",
    EXPENSIVE: "cheaper_leads",
    STARVED: "more_delivery",
    IDLE: "delivery_resumes",
    JUNK: "spend_stops",
    # Graded on what the group was bought for, the figure that decided the
    # proposal - never on the click rate that explains it. See
    # :func:`_cheaper_results`.
    SATURATED: "cheaper_results",
    NARROW_AUDIENCE: "cheaper_reported_leads",
    # The one promise not about the object the change was made to. Switching
    # an advert off is graded on the **group** it sat in, because that is
    # what it was meant to help - see :func:`_group_gets_cheaper`.
    WEAK_AD: "cheaper_group_leads",
    # The two whose subject is the provider. They promise what the two
    # rules above them promise and are graded by the same two checks -
    # taking a dead audience out is meant to start delivery again, and
    # accepting the provider's advice is meant to buy more of it - which
    # is deliberate: a promise invented for a new rule is a promise with
    # no test behind it.
    PROVIDER_STOPPED: "delivery_resumes",
    PROVIDER_ADVICE: "more_delivery",
    # The second promise about a group made through one of its adverts. The
    # advert that gets a new picture is switched off and replaced by one with
    # a new id, so the group is the only thing whose figures continue.
    REFRESH_AD: "group_cheaper_results",
    # A new picture is a new advert with a new id, for the reason above -
    # so the promise is the group's: it delivers again.
    BROKEN_PICTURE: "group_delivery_resumes",
    REFUSED_AD: "group_delivery_resumes",
    SITE_DOWN: "spend_stops",
}

# The promises whose aftermath is the parent group's rather than the
# object's own - see ``core.agent.assess.JUDGED_ON_PARENT``.
PARENT_PROMISES: Final = frozenset(
    {
        "cheaper_group_leads",
        "group_attention_recovers",
        "group_cheaper_results",
        "group_delivery_resumes",
    }
)


class Check(Protocol):
    def __call__(
        self, *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
    ) -> "Verdict | None": ...


def _spend_stops(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """A pause is proved by absence. No rows after the stop *is* the success
    it predicted - a paused ad set produces no figures at all - which is why
    nought days is an answer here and a question everywhere else."""
    worked = after.totals.spend_minor == 0
    return Verdict(
        outcome=WORKED if worked else NOT_WORKED,
        figures=figures(WASTING, after),
    )


def _delivery_resumes(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """A resume is proved only by presence - the asymmetry with the pause
    above. Absence is ambiguous: not delivering yet, or a sync that has not
    caught up. Only spend proves the answer, so silence stays ``None``."""
    if after.totals.spend_minor > 0:
        return Verdict(outcome=WORKED, figures=figures(IDLE, after))
    return None


def _more_leads(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """More budget should buy more leads at no worse a price.

    Both halves, deliberately: a raise that lifts the count by buying dear
    leads has moved money, not results. The price bound is the evidence's
    own cost per lead - strict, because "no worse" was the promise. Leads
    are counted the larger way on both sides, as the rule counted them.

    A group bought for something else is graded on that - see
    :func:`_more_results`."""
    if _priced_as_other(evidence):
        return _more_results(evidence=evidence, after=after, min_days=min_days)
    if after.days < min_days:
        return None
    before_rate = rate(evidence.get("leads"), evidence.get("days"))
    if before_rate is None:
        return Verdict(outcome=UNCLEAR, figures=figures(WINNING, after))

    grew = _lead_count(after) / after.days > before_rate
    before_cost = as_int(evidence.get("cpl_minor"))
    cost = lead_cost(after.totals)
    held = before_cost is None or (cost is not None and cost <= before_cost)
    return Verdict(
        outcome=WORKED if grew and held else NOT_WORKED,
        figures=figures(WINNING, after),
    )


def _cheaper_leads(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """Less budget should mean a lower cost per lead - and leads still
    arriving. An aftermath with no lead at all is not a cheaper campaign,
    it is a stopped one arrived at slowly. A group bought for something
    else is graded on the price of that."""
    if _priced_as_other(evidence):
        return _cheaper_results(
            EXPENSIVE, evidence=evidence, after=after, min_days=min_days
        )
    if after.days < min_days:
        return None
    before_cost = as_int(evidence.get("cpl_minor"))
    if before_cost is None:
        return Verdict(outcome=UNCLEAR, figures=figures(EXPENSIVE, after))

    cost = lead_cost(after.totals)
    worked = cost is not None and cost < before_cost
    return Verdict(
        outcome=WORKED if worked else NOT_WORKED,
        figures=figures(EXPENSIVE, after),
    )


def _priced_as_other(evidence: Mapping[str, Any]) -> bool:
    """Whether a price rule judged this group by something other than leads."""
    return str(evidence.get("outcome") or "lead") != "lead"


def _more_results(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """More budget should buy more of the group's own result at no worse a price.

    :func:`_more_leads` for a conversation, a call or a visit: both halves,
    counted and priced the way the rule counted and priced them.
    """
    if after.days < min_days:
        return None
    family = str(evidence.get("outcome") or "")
    before_rate = rate(evidence.get("results"), evidence.get("days"))
    count = count_in(totals=after.totals, link_clicks=after.link_clicks, family=family)
    shown = {**figures(WINNING, after), "outcome": family, "result_count": count}
    if before_rate is None or count is None:
        return Verdict(outcome=UNCLEAR, figures=shown)
    before_cost = as_int(evidence.get("cost_minor"))
    cost = result_cost(spend_minor=after.totals.spend_minor, count=count, family=family)
    grew = count / after.days > before_rate
    held = before_cost is None or (cost is not None and cost <= before_cost)
    return Verdict(outcome=WORKED if grew and held else NOT_WORKED, figures=shown)


def _lead_count(after: Aftermath) -> int:
    return max(after.totals.leads, after.totals.leads_reported)


def _more_delivery(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """A wider audience should let the ad set spend what it is allowed."""
    if after.days < min_days:
        return None
    before_rate = rate(evidence.get("spend_minor"), evidence.get("days"))
    if before_rate is None:
        return Verdict(outcome=UNCLEAR, figures=figures(STARVED, after))

    worked = after.totals.spend_minor / after.days > before_rate
    return Verdict(
        outcome=WORKED if worked else NOT_WORKED,
        figures=figures(STARVED, after),
    )


def _attention_recovers(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """A fresher audience should click again.

    Graded on the figure the rule fired on - link clicks over impressions,
    in ten-thousandths - and against the *later* half of the evidence,
    which is the worn state the change was meant to undo. Beating the
    early half was never the promise: some of that fall is the ad ageing
    and no audience change reverses it."""
    if after.days < min_days:
        return None
    before = as_int(evidence.get("late_ctr_bp"))
    ctr = ctr_bp(clicks=after.link_clicks, impressions=after.totals.impressions)
    if before is None or ctr is None:
        return Verdict(outcome=UNCLEAR, figures=figures(SATURATED, after))

    return Verdict(
        outcome=WORKED if ctr > before else NOT_WORKED,
        figures=figures(SATURATED, after),
    )


def _cheaper_reported_leads(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """Cutting a dead slice out of the audience should lower what a lead costs.

    The provider's own lead count on both sides, and it has to be: a
    segment carries no lead of ours, so the decision was made on the
    provider's figure and the grading cannot quietly switch to a better
    one - see the note in ``core.metrics.segment_compare``."""
    if after.days < min_days:
        return None
    before = rate(evidence.get("spend_minor"), evidence.get("leads_reported"))
    cost = rate(after.totals.spend_minor, after.totals.leads_reported)
    if before is None:
        return Verdict(outcome=UNCLEAR, figures=figures(NARROW_AUDIENCE, after))

    return Verdict(
        outcome=WORKED if cost is not None and cost < before else NOT_WORKED,
        figures=figures(NARROW_AUDIENCE, after),
    )


def _group_gets_cheaper(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """Switching off the advert that returned nothing should make the group
    cheaper - and leave it spending.

    **The aftermath here is the group's, not the advert's.** Grading the
    advert would be grading the pause: it stopped, so it spent nothing, and
    every such change would pass. What was promised is that the same budget,
    now going only to the adverts that work, buys leads at a lower price -
    so that is what is read, and the caller supplies the parent's figures.

    A group that has stopped spending altogether answers ``UNCLEAR`` rather
    than failing. Something else happened to it - the owner paused it, its
    campaign ended - and a division by an empty aftermath would report that
    as this change having gone wrong."""
    if after.days < min_days:
        return None
    if after.totals.spend_minor <= 0:
        return Verdict(outcome=UNCLEAR, figures=figures(WEAK_AD, after))

    before = rate(
        evidence.get("adset_spend_minor"), evidence.get("adset_leads_reported")
    )
    cost = rate(after.totals.spend_minor, after.totals.leads_reported)
    if before is None:
        return Verdict(outcome=UNCLEAR, figures=figures(WEAK_AD, after))

    return Verdict(
        outcome=WORKED if cost is not None and cost < before else NOT_WORKED,
        figures=figures(WEAK_AD, after),
    )


def _group_attention_recovers(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """A new advert should bring the group's clicks back up.

    **The group's aftermath, for the reason** :func:`_group_gets_cheaper`
    **gives and one more.** The advert that got new words is switched off,
    and the one that replaced it has an id nobody wrote down - so the group
    is the only object whose figures run through the change.

    Graded on the rate the diagnosis quoted - the group's link clicks over
    impressions for the whole window - and the bar is that it rose. Not
    that it reached the account's average: that is the aim printed on the
    card, and a change that moved the rate halfway there did what it said.
    """
    assert isinstance(after, Aftermath)
    if after.days < min_days:
        return None
    before = as_int(evidence.get("link_ctr_bp"))
    ctr = ctr_bp(clicks=after.link_clicks, impressions=after.totals.impressions)
    if after.totals.spend_minor <= 0 or before is None or ctr is None:
        return Verdict(outcome=UNCLEAR, figures=figures(REFRESH_AD, after))

    return Verdict(
        outcome=WORKED if ctr > before else NOT_WORKED,
        figures=figures(REFRESH_AD, after),
    )


def _cheaper_results(
    rule: str, *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """One of the results the group was bought for should cost less.

    **The figure the proposal was decided on, on both sides.** The evidence
    stored which kind of result the group is judged by and what one cost;
    the aftermath is counted as that kind and priced the same way - a
    conversation as a conversation, a thousand showings as a thousand.

    A group that stopped spending cannot say, for the reason
    :func:`_group_gets_cheaper` gives. Money spent since with nothing to
    show is not a cheaper group, it is the change having failed.
    """
    if after.days < min_days:
        return None
    family = str(evidence.get("outcome") or "")
    before = as_int(evidence.get("cost_minor"))
    count = count_in(totals=after.totals, link_clicks=after.link_clicks, family=family)
    cost = result_cost(spend_minor=after.totals.spend_minor, count=count, family=family)
    shown = {
        **figures(rule, after),
        "outcome": family,
        "result_count": count,
        "cost_minor": cost,
    }
    if after.totals.spend_minor <= 0 or before is None or count is None:
        return Verdict(outcome=UNCLEAR, figures=shown)
    return Verdict(
        outcome=WORKED if cost is not None and cost < before else NOT_WORKED,
        figures=shown,
    )


def _audience_gets_cheaper(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """A wider audience should bring the group's result back to its price.

    A proposal whose evidence carries no price is graded on the click rate
    it was made on, which is the only figure it stored.
    """
    if "cost_minor" not in evidence:
        return _attention_recovers(evidence=evidence, after=after, min_days=min_days)
    return _cheaper_results(
        SATURATED, evidence=evidence, after=after, min_days=min_days
    )


def _new_picture_gets_cheaper(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """A new picture should bring the group's result back to its price.

    The group's aftermath, as for every advert-level promise. A proposal
    whose evidence carries no price is graded on the click rate it was made
    on, for the reason :func:`_audience_gets_cheaper` gives.
    """
    if "cost_minor" not in evidence:
        return _group_attention_recovers(
            evidence=evidence, after=after, min_days=min_days
        )
    return _cheaper_results(
        REFRESH_AD, evidence=evidence, after=after, min_days=min_days
    )


def _group_delivers(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """A replaced picture is proved when the group spends again - by
    presence, for the reason :func:`_delivery_resumes` gives."""
    if after.totals.spend_minor > 0:
        return Verdict(outcome=WORKED, figures=figures(BROKEN_PICTURE, after))
    return None


CHECKS: Final[dict[str, Check]] = {
    REFRESH_AD: _new_picture_gets_cheaper,
    BROKEN_PICTURE: _group_delivers,
    REFUSED_AD: _group_delivers,
    SITE_DOWN: _spend_stops,
    WASTING: _spend_stops,
    JUNK: _spend_stops,
    IDLE: _delivery_resumes,
    WINNING: _more_leads,
    EXPENSIVE: _cheaper_leads,
    STARVED: _more_delivery,
    SATURATED: _audience_gets_cheaper,
    NARROW_AUDIENCE: _cheaper_reported_leads,
    WEAK_AD: _group_gets_cheaper,
    PROVIDER_STOPPED: _delivery_resumes,
    PROVIDER_ADVICE: _more_delivery,
}


def figures(rule: str, after: Aftermath) -> dict[str, Any]:
    """The aftermath as stored: raw sums plus the promise they answered.

    Sums rather than rates - the rates are derivable and a stored rounded
    rate is a second version of the truth. ``expected`` rides along so the
    history screen can say what the question was without re-deriving it."""
    cost = lead_cost(after.totals)
    return {
        "expected": EXPECTATIONS.get(rule, ""),
        "days": after.days,
        "spend_minor": after.totals.spend_minor,
        "impressions": after.totals.impressions,
        "link_clicks": after.link_clicks,
        "leads": after.totals.leads,
        "leads_reported": after.totals.leads_reported,
        "results": after.totals.results,
        "recallers": after.totals.recallers,
        "profile_visits": after.totals.profile_visits,
        "cpl_minor": int(cost) if cost is not None else None,
    }


def rate(total: Any, per: Any) -> float | None:
    """One stored value over another, or nothing.

    ``None`` for anything missing or empty: evidence written by an older
    version of a rule is a real thing to meet, and a comparison against a
    guessed nought would produce a confident verdict from no data."""
    amount = as_int(total)
    span = as_int(per)
    if amount is None or span is None or span <= 0:
        return None
    return amount / span


def as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except ValueError:
        return None


__all__ = [
    "CHECKS",
    "EXPECTATIONS",
    "GONE",
    "NOT_WORKED",
    "PARENT_PROMISES",
    "UNCLEAR",
    "WORKED",
    "Check",
    "as_int",
    "figures",
    "rate",
]
