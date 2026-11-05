"""The divisions every figure is built from, written once.

Three shapes and no more. A cost is money over a count and stays in minor
units. A percentage and a ratio are exact decimals rounded to hundredths,
because an expert reads a CTR of 1.47% and a whole-number 1% hides the
difference between a creative that works and one that does not.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from adskit import MinorUnits

HUNDREDTHS: Final = Decimal("0.01")


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


def percent(*, part: int, whole: int) -> Decimal | None:
    """``part`` as a percentage of ``whole``, to hundredths. Nothing over nought."""
    if whole <= 0:
        return None
    return (Decimal(part) * 100 / Decimal(whole)).quantize(
        HUNDREDTHS, rounding=ROUND_HALF_UP
    )


def ratio(*, part: int, whole: int) -> Decimal | None:
    """``part`` over ``whole``, to hundredths. Nothing over nought."""
    if whole <= 0:
        return None
    return (Decimal(part) / Decimal(whole)).quantize(HUNDREDTHS, rounding=ROUND_HALF_UP)


__all__ = ["HUNDREDTHS", "cost_per", "percent", "ratio"]
