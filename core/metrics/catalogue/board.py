"""What the expert dashboard says about a range, beyond each metric.

The funnel's steps, the campaigns ranked against their own goal's average,
and the adverts that need looking at. Every number is the catalogue's;
this only decides which ones to put side by side.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from core.metrics import formulas
from core.metrics.arithmetic import hundredths, whole_number
from core.metrics.catalogue import Answer, Figures, Setting, compute, missing
from core.metrics.catalogue.common import leads, sales
from core.metrics.catalogue.meta import (
    FREQUENCY_HIGH,
    HOLD_WEAK_PCT,
    HOOK_WEAK_PCT,
    LOW_RANKINGS,
    RANKED_FROM,
)
from core.metrics.outcomes import Outcome

# A campaign is ranked once it has this many results, and not before: two
# leads are a coin toss, not a price.
MIN_RANKED_RESULTS: Final = 5
RANKED_EACH_SIDE: Final = 5
TROUBLED_ADS: Final = 10


# -- the funnel ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Step:
    key: str
    label: str
    count: Answer
    # From the step above; nothing on the first step.
    rate: Answer | None = None


def funnel(figures: Figures, setting: Setting) -> tuple[Step, ...]:
    """Shown, clicked, a lead, qualified, sold - and the share between each."""
    counts: list[tuple[str, str, Answer]] = [
        ("impressions", "Ko'rsatildi", Answer(value=figures.impressions)),
        ("link_clicks", "Link klik", compute("link_clicks", figures, setting)),
        ("leads", "Lid", Answer(value=leads(figures, setting))),
        ("qualified", "Sifatli lid", compute("qualified", figures, setting)),
        ("sales", "Sotuv", _sales(figures, setting)),
    ]
    steps: list[Step] = []
    for index, (key, label, count) in enumerate(counts):
        if index == 0:
            steps.append(Step(key=key, label=label, count=count))
            continue
        above = counts[index - 1][2]
        steps.append(Step(key=key, label=label, count=count, rate=_rate(count, above)))
    return tuple(steps)


def _sales(figures: Figures, setting: Setting) -> Answer:
    if setting.outcome not in ("site_lead", "click", "none") and not figures.crm:
        return missing("no_crm")
    return Answer(value=sales(figures, setting))


def _rate(count: Answer, above: Answer) -> Answer:
    if not count.known or not above.known:
        return missing(count.missing or above.missing or "no_base")
    found = hundredths(formulas.step_rate(int(count.value), int(above.value)))  # type: ignore[arg-type]
    return Answer(value=found) if found is not None else missing("no_base")


# -- the campaigns against their goal ----------------------------------------------


@dataclass(frozen=True, slots=True)
class Ranked:
    id: str
    outcome: Outcome
    cost: Answer
    # A hundred is the goal's average; below is cheaper.
    index: int | None


def ranked(
    rows: Sequence[tuple[str, Figures, Setting]], *, totals: dict[Outcome, Figures]
) -> tuple[tuple[Ranked, ...], tuple[Ranked, ...]]:
    """The cheapest and the dearest campaigns, each against its own goal.

    A campaign with too few results is not ranked cheap. One that spent
    more than its goal's average price and brought nothing is ranked dear.
    """
    found: list[Ranked] = []
    for one, figures, setting in rows:
        cost = compute("cost_per_result", figures, setting)
        goal = totals.get(setting.outcome)
        average = (
            compute("cost_per_result", goal, setting) if goal is not None else None
        )
        if average is None or not average.known:
            continue
        count = compute("results", figures, setting)
        if cost.known and int(count.value or 0) >= MIN_RANKED_RESULTS:  # type: ignore[arg-type]
            index = whole_number(
                formulas.cost_index(int(cost.value), int(average.value))  # type: ignore[arg-type]
            )
            found.append(Ranked(one, setting.outcome, cost, index))
        elif not count.value and figures.spend_minor > int(average.value):  # type: ignore[arg-type]
            found.append(Ranked(one, setting.outcome, cost, None))
    priced = sorted((r for r in found if r.index is not None), key=lambda r: r.index)  # type: ignore[arg-type, return-value]
    barren = [r for r in found if r.index is None]
    best = tuple(r for r in priced if r.index is not None and r.index < 100)
    worst = tuple(barren) + tuple(
        r for r in reversed(priced) if r.index is not None and r.index > 100
    )
    return best[:RANKED_EACH_SIDE], worst[:RANKED_EACH_SIDE]


# -- the adverts that need looking at -------------------------------------------------


@dataclass(frozen=True, slots=True)
class Trouble:
    key: str
    value: Decimal | str
    norm: str


def troubles(figures: Figures, setting: Setting) -> tuple[Trouble, ...]:
    """Which of an advert's figures are past their norm. Nothing below the
    impressions Meta needs to rank, where every rate is noise."""
    if figures.impressions < RANKED_FROM:
        return ()
    found: list[Trouble] = []
    hook = compute("hook_rate", figures, setting)
    if hook.known and Decimal(str(hook.value)) < HOOK_WEAK_PCT:
        found.append(Trouble("hook_rate", hook.value, f"{HOOK_WEAK_PCT}% dan past"))  # type: ignore[arg-type]
    hold = compute("hold_rate", figures, setting)
    if hold.known and Decimal(str(hold.value)) < HOLD_WEAK_PCT:
        found.append(Trouble("hold_rate", hold.value, f"{HOLD_WEAK_PCT}% dan past"))  # type: ignore[arg-type]
    often = compute("frequency", figures, setting)
    if often.known and Decimal(str(often.value)) > FREQUENCY_HIGH:
        found.append(Trouble("frequency", often.value, f"{FREQUENCY_HIGH} dan yuqori"))  # type: ignore[arg-type]
    for key in (
        "quality_ranking",
        "engagement_rate_ranking",
        "conversion_rate_ranking",
    ):
        verdict = compute(key, figures, setting)
        if verdict.known and verdict.value in LOW_RANKINGS:
            found.append(Trouble(key, str(verdict.value), "pastki 20%"))
    return tuple(found)


__all__ = [
    "MIN_RANKED_RESULTS",
    "Ranked",
    "Step",
    "Trouble",
    "funnel",
    "ranked",
    "troubles",
]
