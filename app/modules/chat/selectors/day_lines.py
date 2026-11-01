"""What one row of the daily message came to: a group, an advert, a pair.

Every row is counted by the same rule at its own rung - the screens' rule,
so the message and the cabinet agree about the same day. A result is
counted in the column the numbers screen counts it in, a lead the way Ads
Manager counts it.

**One step past the screens: a goal they call uncounted.** A campaign bought
for a registration has no column of its own, yet Meta reports what it brought,
and calling most of an account's money "not counted" tells the owner less than
Meta already did. The report prints Meta's count under the goal's own name.

**Kinds are never added together.** Eight kinds of result are counted on
eight scales, and adding a conversation to an enquiry is the one piece of
arithmetic this product never does. A row bought for two things says two
counts, each priced over its own money.
"""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Final

from adskit import MinorUnits

from app.common.money import format_minor, number_format
from app.modules.metrics.selectors.results import words_for
from core.chat.daily import NO_FIGURE
from core.chat.day_report import Figure, Result
from core.metrics import cost_per, counted_leads, measured
from core.metrics.outcomes import SITE_GOAL, site_event

REGISTRATION: Final = "registration"
MESSAGE_PURCHASE: Final = "message_purchase"
OTHER_RESULT: Final = "other"
REGISTRATION_EVENT: Final = "COMPLETE_REGISTRATION"
MESSAGE_PURCHASE_GOAL: Final = "MESSAGING_PURCHASE_CONVERSION"

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
    # Goals the screens leave uncounted: Meta's own «Results» column.
    REGISTRATION: "results",
    MESSAGE_PURCHASE: "results",
    OTHER_RESULT: "results",
}

# One part of a row: what it was bought for, its summed figures, and the
# enquiries of ours that came through it.
Part = tuple[str, Mapping[str, int], int]


def report_money(amount_minor: int, currency: str) -> str:
    """Money as the report prints it: cents always, so the lines read alike."""
    return format_minor(amount_minor=amount_minor, currency=currency, keep_cents=True)


def change_text(now: int, before: int) -> str:
    """«+94%», or nothing with no earlier money to measure against."""
    if before <= 0:
        return ""
    moved = round((now - before) * 100 / before)
    return f"+{number_format(moved)}%" if moved > 0 else f"{number_format(moved)}%"


def report_kind(
    outcome: str, *, goal: str, promoted: Mapping[str, object] | None
) -> str:
    """The kind a group is reported under: its outcome, or a name for a goal
    the screens leave uncounted."""
    if outcome != "none":
        return outcome
    wanted = goal.strip().upper()
    if wanted == MESSAGE_PURCHASE_GOAL:
        return MESSAGE_PURCHASE
    if wanted == SITE_GOAL and site_event(promoted) == REGISTRATION_EVENT:
        return REGISTRATION
    return OTHER_RESULT


def figure_of(*, parts: Iterable[Part], currency: str) -> Figure:
    """The money and the results of these parts, one count per kind."""
    spend = uncounted = 0
    counted: dict[str, list[int]] = {}
    for kind, sums, ours in parts:
        money = int(sums.get("spend", 0) or 0)
        spend += money
        if kind != "lead" and kind not in COUNTED:
            uncounted += money
            continue
        tally = counted.setdefault(kind, [0, 0])
        tally[0] += result_count(kind=kind, sums=sums, ours=ours)
        tally[1] += money
    # A goal with no name of its own and nothing from Meta really is uncounted.
    silent = counted.get(OTHER_RESULT)
    if silent is not None and not silent[0]:
        uncounted += silent[1]
        del counted[OTHER_RESULT]
    return Figure(
        spend=report_money(spend, currency),
        spend_minor=spend,
        # The kind the most money went on first, so a pair bought mostly
        # for enquiries does not open with its handful of calls.
        results=tuple(
            _result(kind=kind, count=count, spend=money, currency=currency)
            for kind, (count, money) in sorted(
                counted.items(), key=lambda item: -item[1][1]
            )
        ),
        uncounted=report_money(uncounted, currency) if uncounted > 0 else "",
    )


def against(figure: Figure, *, before: Figure) -> Figure:
    """``figure`` with each goal's count and cost over the period before."""
    earlier = {result.kind: result for result in before.results}
    return replace(
        figure,
        results=tuple(
            _beside(result, earlier.get(result.kind), before=before)
            for result in figure.results
        ),
    )


def _beside(result: Result, held: Result | None, *, before: Figure) -> Result:
    if held is not None:
        return replace(
            result,
            before_spend=held.spend,
            before_count=held.count,
            before_cost=held.cost,
        )
    if result.kind == OTHER_RESULT and before.uncounted:
        return replace(result, before_spend=before.uncounted)
    return result


def result_count(*, kind: str, sums: Mapping[str, int], ours: int) -> int:
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


def _result(*, kind: str, count: int, spend: int, currency: str) -> Result:
    words = words_for(kind)  # type: ignore[arg-type]
    cost = cost_per(MinorUnits(spend * words.per), count)
    return Result(
        kind=kind,
        count=count,
        word=str(words.one),
        cost=NO_FIGURE if cost is None else report_money(cost, currency),
        spend=report_money(spend, currency),
        per_thousand=words.per > 1,
    )


__all__ = [
    "COUNTED",
    "Part",
    "against",
    "change_text",
    "figure_of",
    "report_kind",
    "report_money",
    "result_count",
]
