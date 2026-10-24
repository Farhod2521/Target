"""What each change promised, and how that promise is tested."""

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

WORKED: Final = "worked"
NOT_WORKED: Final = "not_worked"
UNCLEAR: Final = "unclear"
GONE: Final = "gone"

EXPECTATIONS: Final[dict[str, str]] = {
    WASTING: "spend_stops",
    WINNING: "more_leads",
    EXPENSIVE: "cheaper_leads",
    STARVED: "more_delivery",
    IDLE: "delivery_resumes",
    JUNK: "spend_stops",
    SATURATED: "cheaper_results",
    NARROW_AUDIENCE: "cheaper_reported_leads",
    WEAK_AD: "cheaper_group_leads",
    PROVIDER_STOPPED: "delivery_resumes",
    PROVIDER_ADVICE: "more_delivery",
    REFRESH_AD: "group_cheaper_results",
    BROKEN_PICTURE: "group_delivery_resumes",
    REFUSED_AD: "group_delivery_resumes",
    SITE_DOWN: "spend_stops",
}

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
    """More budget should buy more leads at no worse a price."""
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
    """More budget should buy more of the group's own result at no worse a price."""
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
    """A fresher audience should click again."""
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
    """Cutting a dead slice out of the audience should lower what a lead costs."""
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
    cheaper - and leave it spending."""
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
    """A new advert should bring the group's clicks back up."""
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
    """One of the results the group was bought for should cost less."""
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
    """A wider audience should bring the group's result back to its price."""
    if "cost_minor" not in evidence:
        return _attention_recovers(evidence=evidence, after=after, min_days=min_days)
    return _cheaper_results(
        SATURATED, evidence=evidence, after=after, min_days=min_days
    )


def _new_picture_gets_cheaper(
    *, evidence: Mapping[str, Any], after: Aftermath, min_days: int
) -> Verdict | None:
    """A new picture should bring the group's result back to its price."""
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
    """The aftermath as stored: raw sums plus the promise they answered."""
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
    """One stored value over another, or nothing."""
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
