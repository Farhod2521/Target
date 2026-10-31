"""What one row of the daily message came to: a group, an advert, a pair.

Every row is counted by the same rule at its own rung - the screens' rule,
so the message and the cabinet agree about the same day. A result is
counted in the column the numbers screen counts it in, a lead the way Ads
Manager counts it.

**Kinds are never added together.** Eight kinds of result are counted on
eight scales, and adding a conversation to an enquiry is the one piece of
arithmetic this product never does. A row bought for two things says two
counts, each priced over its own money.
"""

from collections.abc import Iterable, Mapping
from typing import Final

from adskit import MinorUnits

from app.common.money import format_minor
from app.modules.metrics.selectors.results import words_for
from core.chat.daily import NO_FIGURE
from core.chat.day_report import Figure, Result
from core.metrics import Outcome, cost_per, counted_leads, measured

# Which summed figure counts one result, per kind. A lead is not here - see
# :func:`result_count`; a kind with no entry has nothing to count.
COUNTED: Final[dict[str, str]] = {
    "chat": "results",
    "call": "results",
    "view": "impressions",
    "click": "results",
    "recall": "recallers",
    "profile": "profile_visits",
    # A lead on the owner's own site: the provider's count.
    "site_lead": "reported",
}

# One part of a row: what it was bought for, its summed figures, and the
# enquiries of ours that came through it.
Part = tuple[Outcome, Mapping[str, int], int]


def figure_of(*, parts: Iterable[Part], currency: str) -> Figure:
    """The money and the results of these parts, one count per kind."""
    spend = 0
    counted: dict[Outcome, list[int]] = {}
    for kind, sums, ours in parts:
        money = int(sums.get("spend", 0) or 0)
        spend += money
        if kind != "lead" and kind not in COUNTED:
            continue
        tally = counted.setdefault(kind, [0, 0])
        tally[0] += result_count(kind=kind, sums=sums, ours=ours)
        tally[1] += money
    return Figure(
        spend=format_minor(amount_minor=spend, currency=currency),
        spend_minor=spend,
        # The kind the most money went on first, so a pair bought mostly
        # for enquiries does not open with its handful of calls.
        results=tuple(
            _result(kind=kind, count=count, spend=money, currency=currency)
            for kind, (count, money) in sorted(
                counted.items(), key=lambda item: -item[1][1]
            )
        ),
        counted=bool(counted),
    )


def result_count(*, kind: Outcome, sums: Mapping[str, int], ours: int) -> int:
    """One part's results. A lead is counted the way Ads Manager counts it -
    see :mod:`core.metrics.lead_count`."""
    if kind == "lead":
        reported = int(sums.get("reported", 0) or 0)
        return counted_leads(
            ours=ours,
            reported=reported,
            measured=measured(
                spend_minor=int(sums.get("spend", 0) or 0),
                impressions=int(sums.get("impressions", 0) or 0),
                reported=reported,
            ),
        )
    field = COUNTED.get(kind)
    return int(sums.get(field, 0) or 0) if field else 0


def _result(*, kind: Outcome, count: int, spend: int, currency: str) -> Result:
    words = words_for(kind)
    cost = cost_per(MinorUnits(spend * words.per), count)
    return Result(
        kind=kind,
        count=count,
        word=str(words.one),
        cost=NO_FIGURE
        if cost is None
        else format_minor(amount_minor=cost, currency=currency),
        per_thousand=words.per > 1,
    )


__all__ = ["COUNTED", "Part", "figure_of", "result_count"]
