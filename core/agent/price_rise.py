"""When one result costs three times what it usually does (TZ 1).

**The usual price is the account's own.** The account's earlier adverts of
the same result - a lead with a lead, a chat with a chat, one website event
with the same event (TZ 3.3) - over the 90 days before the window, each
with at least 1 000 impressions and 5 results; the median of their cost per
result, and of every funnel figure beside it (TZ 1.2). With fewer than three
such adverts the account has no history and the niche's adverts stand in
for it; with neither, nothing is said.

**Three days, three times.** The last three finished days' cost per result
against the usual price; with no result at all, the money spent against
three usual prices (TZ 1.3). Under twice the usual price a group starts
again (TZ 1.6).

**Why, in at most two causes.** Every funnel step is held against its usual
level as ``now ÷ usual`` and called a cause past its bar (TZ 1.4); the
causes furthest from usual come first. Meta's own rankings have no ratio
and come after them. With no step past its bar the message says so.

Pure, like the rest of ``core``: figures arrive as plain values and the
answer is a decision, not a write.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median
from typing import Final, Literal

from core.metrics import formulas

Source = Literal["account_history", "niche_average"]
CauseKey = Literal[
    "cpm", "frequency", "hook", "hold", "ctr", "cpc", "conversion", "ranking"
]

# TZ 1.2: which adverts make the usual price, and how many of them.
HISTORY_DAYS: Final = 90
MIN_IMPRESSIONS: Final = 1_000
MIN_RESULTS: Final = 5
MIN_ADVERTS: Final = 3

# TZ 1.3 and 1.6: the window, the bar, and where a group starts again.
WINDOW_DAYS: Final = 3
RISE: Final = 3
RESET_UNDER: Final = 2

# TZ 1.4: the bars of ``now ÷ usual``. "Up" figures are worse higher.
UP_BAR: Final = 1.5
FREQUENCY_BAR: Final = 2.0
DOWN_BAR: Final = 0.7
MAX_CAUSES: Final = 2

# Meta's rankings, worst last; at or past BELOW_AVERAGE_20 is a cause.
RANKINGS: Final = (
    "above_average",
    "average",
    "below_average_35",
    "below_average_20",
    "below_average_10",
)
RANKING_BAR: Final = RANKINGS.index("below_average_20")


@dataclass(frozen=True, slots=True)
class Figures:
    """One advert's or group's figures over some days, as the funnel reads them.

    ``reach`` is people counted once over the days, not a sum of days; ``0``
    when it is not known. ``chat``: a messages advert, whose last step is
    results over every click (TZ 1.4). ``rankings`` are Meta's three, by
    name, the newest known.
    """

    spend_minor: int = 0
    impressions: int = 0
    results: int = 0
    link_clicks: int = 0
    clicks: int = 0
    reach: int = 0
    views_3s: int = 0
    thruplays: int = 0
    chat: bool = False
    rankings: dict[str, str] = field(default_factory=dict)

    @property
    def is_video(self) -> bool:
        return self.views_3s > 0

    @property
    def cost(self) -> int | None:
        """Cost per result, in minor units."""
        return formulas.cost_per_result(self.spend_minor, self.results)

    def value(self, key: CauseKey) -> float | None:
        """One funnel figure: money in minor units, rates in percent."""
        found: Decimal | int | None = None
        if key == "cpm":
            found = formulas.cpm(self.spend_minor, self.impressions)
        elif key == "frequency":
            found = formulas.frequency(self.impressions, self.reach)
        elif key == "hook" and self.is_video:
            found = formulas.hook_rate(self.views_3s, self.impressions)
        elif key == "hold" and self.is_video:
            found = formulas.hold_rate(self.thruplays, self.views_3s)
        elif key == "ctr":
            found = formulas.ctr(self.link_clicks, self.impressions)
        elif key == "cpc":
            found = formulas.cpc(self.spend_minor, self.link_clicks)
        elif key == "conversion":
            # TZ 1.4: a messages advert's last step is results over every click.
            step = self.clicks if self.chat else self.link_clicks
            found = formulas.form_conversion(self.results, step)
        return None if found is None else float(found)


STEPS: Final[tuple[tuple[CauseKey, str, float], ...]] = (
    ("cpm", "up", UP_BAR),
    ("frequency", "up", FREQUENCY_BAR),
    ("hook", "down", DOWN_BAR),
    ("hold", "down", DOWN_BAR),
    ("ctr", "down", DOWN_BAR),
    ("cpc", "up", UP_BAR),
    ("conversion", "down", DOWN_BAR),
)


@dataclass(frozen=True, slots=True)
class Usual:
    """The usual level: the median cost per result and of every step."""

    cost: float
    steps: dict[str, float]
    source: Source
    adverts: int


def qualifies(item: Figures) -> bool:
    """TZ 1.2: an advert that says something about the usual price."""
    return item.impressions >= MIN_IMPRESSIONS and item.results >= MIN_RESULTS


def usual_of(adverts: Iterable[Figures], *, source: Source) -> Usual | None:
    """The median of the adverts that qualify, or nothing under three of them.

    A step's median is read only over the adverts that have the step - the
    hook and hold over the video ones - and only when three of them do.
    """
    kept = [item for item in adverts if qualifies(item)]
    if len(kept) < MIN_ADVERTS:
        return None
    steps: dict[str, float] = {}
    for key, _way, _bar in STEPS:
        values = [v for v in (item.value(key) for item in kept) if v is not None]
        if len(values) >= MIN_ADVERTS:
            steps[key] = median(values)
    costs = [item.cost for item in kept if item.cost is not None]
    return Usual(cost=median(costs), steps=steps, source=source, adverts=len(kept))


def risen(now: Figures, usual: Usual) -> bool:
    """TZ 1.3: three times the usual price - or, with nothing back, three
    usual prices spent."""
    if now.results:
        return now.spend_minor >= RISE * usual.cost * now.results
    return now.spend_minor >= RISE * usual.cost


def eased(now: Figures, usual: Usual) -> bool:
    """TZ 1.6: under twice the usual price, the group starts again."""
    return (
        bool(now.results) and now.spend_minor < RESET_UNDER * usual.cost * now.results
    )


def times(now: Figures, usual: Usual) -> float:
    """How many usual prices one result costs now - or, with none, were spent."""
    spent = now.cost if now.results else now.spend_minor
    return float(formulas.cost_index(spent or 0, round(usual.cost)) or 0) / 100


@dataclass(frozen=True, slots=True)
class Cause:
    """One step past its bar: its figure now and usually, and how far apart."""

    key: CauseKey
    now: float
    usual: float
    ratio: float
    # For the rankings: which one, and its value; ``now``/``usual`` are 0.
    ranking: str = ""
    level: str = ""


def causes(now: Figures, usual: Usual) -> list[Cause]:
    """TZ 1.4: the steps past their bars, furthest first, at most two."""
    found: list[Cause] = []
    for key, way, bar in STEPS:
        current, normal = now.value(key), usual.steps.get(key)
        if current is None or not normal:
            continue
        ratio = current / normal
        if (way == "up" and ratio >= bar) or (way == "down" and ratio <= bar):
            found.append(Cause(key=key, now=current, usual=normal, ratio=ratio))
    # TZ 1.4: a dearer click is the CPM's or the CTR's doing - said by itself
    # only when neither of them is.
    if any(cause.key in ("cpm", "ctr") for cause in found):
        found = [cause for cause in found if cause.key != "cpc"]
    found.sort(key=lambda cause: -_distance(cause.ratio))
    ranked = _ranking(now.rankings)
    if ranked is not None:
        found.append(ranked)
    return found[:MAX_CAUSES]


def _distance(ratio: float) -> float:
    """How far from usual, the same either way: 0.5 is as far as 2."""
    return max(ratio, 1 / ratio) if ratio > 0 else float("inf")


def _ranking(rankings: dict[str, str]) -> Cause | None:
    """The worst of Meta's rankings at or past BELOW_AVERAGE_20, or none."""
    worst: tuple[int, str, str] | None = None
    for name in ("quality", "engagement", "conversion"):
        value = (rankings.get(name) or "").lower()
        if value not in RANKINGS:
            continue
        place = RANKINGS.index(value)
        if place >= RANKING_BAR and (worst is None or place > worst[0]):
            worst = (place, name, value)
    if worst is None:
        return None
    return Cause(
        key="ranking", now=0, usual=0, ratio=0, ranking=worst[1], level=worst[2]
    )


__all__ = [
    "HISTORY_DAYS",
    "MAX_CAUSES",
    "MIN_ADVERTS",
    "MIN_IMPRESSIONS",
    "MIN_RESULTS",
    "RESET_UNDER",
    "RISE",
    "WINDOW_DAYS",
    "Cause",
    "CauseKey",
    "Figures",
    "Source",
    "Usual",
    "causes",
    "eased",
    "qualifies",
    "risen",
    "times",
    "usual_of",
]
