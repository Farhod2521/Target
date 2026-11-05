"""The divisions every figure is built from, written once.

A cost is money over a count and stays in minor units. A rate is an exact
decimal, rounded only where it is shown: to hundredths for an expert, who
reads a CTR of 1.47% and not 1%, or to a whole number or basis points for a
screen or a rule that was built on those. Rounding the hundredths again
would round twice, so each representation is taken from the exact value.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from adskit import MinorUnits

HUNDREDTHS: Final = Decimal("0.01")
WHOLE: Final = Decimal(1)
BASIS_POINTS: Final = 10_000


def cost_per(spend_minor: MinorUnits, count: int) -> MinorUnits | None:
    """Cost per one of something, or nothing when the division says nothing.

    **The only place this division is written.** Spread over several call
    sites, some would carry both refusals below and some only one, and the
    difference would not be visibly wrong: a screen that tests the result
    for truth before printing it treats nought as false. A guard that holds
    by luck downstream is a guard that stops holding the day somebody
    prints the figure without the test.

    Two refusals.

    **No count**: dividing by nought has no answer, and a range with spend
    and no leads is the most expensive state a campaign can be in rather
    than a free one.

    **No spend**: the arithmetic works and the answer is a lie. Leads
    arrive continuously and figures are collected once a night, so an
    account looked at before its first sync of the day has today's leads
    against nothing spent - and it would be told each one cost nothing.
    That is the same reading a cabinet gets when its leads come from
    somewhere its spend does not, which is the failure this pair of guards
    exists to make impossible to show.

    Nought is never the honest answer here. Where it is arithmetically
    true - leads that arrived with no advertising behind them - a *cost*
    per lead is not the figure being asked for anyway.
    """
    if count <= 0 or spend_minor <= 0:
        return None
    return MinorUnits(round(spend_minor / count))


def exact_percent(*, part: int, whole: int) -> Decimal | None:
    """``part`` as a percentage of ``whole``, unrounded. Nothing over nought."""
    if whole <= 0:
        return None
    return Decimal(part) * 100 / Decimal(whole)


def exact_ratio(*, part: int, whole: int) -> Decimal | None:
    """``part`` over ``whole``, unrounded. Nothing over nought."""
    if whole <= 0:
        return None
    return Decimal(part) / Decimal(whole)


def hundredths(value: Decimal | None) -> Decimal | None:
    """An exact rate to two places, as an expert's table shows it."""
    if value is None:
        return None
    return value.quantize(HUNDREDTHS, rounding=ROUND_HALF_UP)


def whole_number(value: Decimal | None) -> int:
    """An exact rate to a whole number. Nothing reads as nought, as before."""
    if value is None:
        return 0
    return int(value.quantize(WHOLE, rounding=ROUND_HALF_UP))


def basis_points(value: Decimal | None) -> int:
    """An exact value in whole hundredths: a percentage in basis points, a
    ratio such as a frequency in hundredths. Nothing reads as nought."""
    if value is None:
        return 0
    return whole_number(value * 100)


def percent(*, part: int, whole: int) -> Decimal | None:
    """``part`` as a percentage of ``whole``, to hundredths."""
    return hundredths(exact_percent(part=part, whole=whole))


def ratio(*, part: int, whole: int) -> Decimal | None:
    """``part`` over ``whole``, to hundredths."""
    return hundredths(exact_ratio(part=part, whole=whole))


def share(*, part: int, whole: int) -> int:
    """``part`` as a whole percentage of ``whole``. Zero divides to zero."""
    return whole_number(exact_percent(part=part, whole=whole))


def rate_bp(*, part: int, whole: int) -> int:
    """``part`` per ten thousand of ``whole``, rounded. Nought over nought."""
    return basis_points(exact_percent(part=part, whole=whole))


def change_pct(*, now: float, before: float) -> int | None:
    """How far ``now`` moved from ``before``, in whole per cent of ``before``."""
    if not before:
        return None
    return round((now - before) * 100 / before)


__all__ = [
    "BASIS_POINTS",
    "HUNDREDTHS",
    "basis_points",
    "change_pct",
    "cost_per",
    "exact_percent",
    "exact_ratio",
    "hundredths",
    "percent",
    "rate_bp",
    "ratio",
    "share",
    "whole_number",
]
