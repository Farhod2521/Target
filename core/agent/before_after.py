"""The figure a change was graded on, before the change and after it.

:mod:`core.agent.promises` answers "did it?"; this answers "from what, to
what". **The same figure the check read, on both sides** - a card printing
a different measure from the one the verdict was decided on would be two
accounts of one change, and the reader would believe the one they can see.

Per day or per lead on both sides, never window totals, for the reason the
checks give: the evidence summed a week and the aftermath sums however many
days have passed since.

A raise has no comparison here: it is graded on two figures at once - more
leads, at no worse a price - and one of them alone would misreport it.

No Django, no clock. Both sides arrive as the stored mappings: ``evidence``
as the approval froze it, ``after`` as the assessment wrote it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from core.agent.facts import ctr_bp
from core.agent.promises import EXPECTATIONS, as_int, rate

Measure = Literal["daily_spend", "link_ctr", "cost_per_lead", "cost_per_result"]


@dataclass(frozen=True, slots=True)
class Change:
    """One figure, before the change and after it.

    ``daily_spend``, ``cost_per_lead`` and ``cost_per_result`` are minor
    units; ``link_ctr`` is ten-thousandths of an impression. ``None`` on the
    after side is a side with nothing to divide by - no lead since the
    change is not a price of nought, and printing one would call a stopped
    campaign a free one.

    ``outcome`` names the result a ``cost_per_result`` is the price of - a
    conversation, a call, a thousand showings - and is empty otherwise.
    """

    measure: Measure
    before: int | None
    after: int | None
    days_before: int | None
    days_after: int | None
    outcome: str = ""


# What each promise is measured in. Keyed on the promise rather than the
# rule, so two rules sharing a promise cannot drift into two measures.
_MEASURES: Final[dict[str, Measure]] = {
    "spend_stops": "daily_spend",
    "delivery_resumes": "daily_spend",
    "group_delivery_resumes": "daily_spend",
    "more_delivery": "daily_spend",
    "attention_recovers": "link_ctr",
    "group_attention_recovers": "link_ctr",
    "cheaper_leads": "cost_per_lead",
    "cheaper_reported_leads": "cost_per_lead",
    "cheaper_group_leads": "cost_per_lead",
    "cheaper_results": "cost_per_result",
    "group_cheaper_results": "cost_per_result",
}

# The click rate a price promise falls back to, for a proposal whose
# evidence carries no price - the only figure such a proposal stored.
_EARLIER: Final[dict[str, str]] = {
    "cheaper_results": "attention_recovers",
    "group_cheaper_results": "group_attention_recovers",
}

# Which stored rate a click-through promise started from. The audience
# change is graded against the worn later half of the window; a new advert
# against the whole window's rate, which is what the diagnosis quoted.
_CTR_KEYS: Final[dict[str, str]] = {
    "attention_recovers": "late_ctr_bp",
    "group_attention_recovers": "link_ctr_bp",
}

# Where the before side of a lead price is read from. The advert rule
# stores the group's own spend and leads under their own keys - its
# promise is about the group - see ``_group_gets_cheaper``.
_PRICE_KEYS: Final[dict[str, tuple[str, str]]] = {
    "cheaper_reported_leads": ("spend_minor", "leads_reported"),
    "cheaper_group_leads": ("adset_spend_minor", "adset_leads_reported"),
}


def before_after(
    *, rule: str, evidence: Mapping[str, Any], after: Mapping[str, Any]
) -> Change | None:
    """The one comparison this rule's verdict rests on, or nothing.

    Nothing when the rule has no measure here, when the aftermath was never
    read - a verdict written because the object is gone or the wait ran out
    carries no sums - or when the before side cannot be read. A comparison
    from a guessed starting point is a claim with no data under it.
    """
    promise = EXPECTATIONS.get(rule, "")
    if promise in _EARLIER and "cost_minor" not in evidence:
        promise = _EARLIER[promise]
    measure = _MEASURES.get(promise)
    if measure is None or as_int(after.get("spend_minor")) is None:
        return None

    if measure == "cost_per_result":
        before = as_int(evidence.get("cost_minor"))
        later = as_int(after.get("cost_minor"))
    elif measure == "daily_spend":
        before = _per_day(evidence.get("spend_minor"), evidence.get("days"))
        later = _per_day(after.get("spend_minor"), after.get("days"))
    elif measure == "link_ctr":
        before = as_int(evidence.get(_CTR_KEYS[promise]))
        later = ctr_bp(
            clicks=as_int(after.get("link_clicks")) or 0,
            impressions=as_int(after.get("impressions")) or 0,
        )
    elif promise == "cheaper_leads":
        # Stored as a price on both sides, counted the larger way - the
        # figure the budget rule fired on and its check graded.
        before = as_int(evidence.get("cpl_minor"))
        later = as_int(after.get("cpl_minor"))
    else:
        spend_key, leads_key = _PRICE_KEYS[promise]
        before = _rounded(rate(evidence.get(spend_key), evidence.get(leads_key)))
        later = _rounded(rate(after.get("spend_minor"), after.get("leads_reported")))

    if before is None:
        return None
    return Change(
        measure=measure,
        before=before,
        after=later,
        days_before=as_int(evidence.get("days")),
        days_after=as_int(after.get("days")),
        outcome=str(evidence.get("outcome") or "")
        if measure == "cost_per_result"
        else "",
    )


def _per_day(total: Any, days: Any) -> int | None:
    """Spend per day. Nought spent is nought a day, however many days.

    The one division where an empty denominator has an answer: a paused
    group writes no rows at all, so its aftermath is nought spent over
    nought days - and that is the success the pause predicted, not a
    figure missing.
    """
    amount = as_int(total)
    if amount == 0:
        return 0
    return _rounded(rate(amount, days))


def _rounded(value: float | None) -> int | None:
    return None if value is None else round(value)


__all__ = ["Change", "Measure", "before_after"]
