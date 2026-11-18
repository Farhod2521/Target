"""The half-hourly guard: what today's figures say needs the owner, or a stop.

Rules written down beforehand and nothing else - no model reads a figure
here and none writes a word about it. Every running group is held against
one usual level (see :class:`Usual`) each time today's figures are read, and
the answer is a short list of findings: a warning, or a stop.

**Only against itself.** The usual level is the group's own and never
another group's: two lead adverts of one account sell different things to
different people, and one's price says nothing about the other's. A group
too new to have a fortnight is held against its own start, and one with no
result yet against its own day's budget - see :func:`_unpriced`.

**What stops, and only what was launched from here.** One result costing
five usual prices; three usual prices gone since the last result with nothing back; three
days run without one result ever; the page
the advert sends people to not opening. A group built in Ads Manager gets
the same finding as a warning: its owner did not hand it over.

**What only warns.** Three usual prices for one result, then four - once
three results are in, or ten usual prices are gone; five usual prices gone
with nothing back, in a group not ours; an advert
inside a group taking a third of the money and bringing nothing while
another brings results; the click rate under 70 % of usual; a thousand
showings at 150 % of usual; a person shown the advert three times a week.

**A new group.** Three results in, their pooled price is its usual one:
nothing back for three of them stops it, and a rise in its price is only
ever a warning - a few days are not a level to stop by. With no price at
all, a day's budget gone with nothing back is a warning, and three days
after the switch-on with still not one result it is stopped.

**One finding a group.** A stop leaves no warning beside it, and a price
rise carries the click rate and the showings' price as its causes instead
of as two more messages. The steps of a rise - 3, 4, 5 - are what a second
message waits for: the same step is never said twice.

**Not in the first day.** A group is judged from 24 hours after it was
switched on. The page not opening is the exception: that is broken, not
unproven.

**Learning is left to learn.** A group still learning is stopped for
nothing back and for a page that is down, and only warned about its price.

Pure, like the rest of ``core``.
"""

from dataclasses import dataclass, field
from typing import Final, Literal

from core.agent.sufficiency import SPEND_MULTIPLE
from core.metrics import formulas
from core.metrics.arithmetic import basis_points_or_none

Kind = Literal["site_down", "fruitless", "price", "weak_ad", "ctr", "cpm", "frequency"]
Action = Literal["warn", "stop"]
Cause = Literal["cpm", "ctr", "conversion"]
# ``own`` is the group's fortnight; ``start`` its first days' pooled price.
Source = Literal["own", "start"]
# The button a message advises, by what pressing it does.
Advice = Literal[
    "pause", "budget_down", "leave", "keep_off", "resume", "pause_ad", "add_creative"
]

# A rise is said at each of these, and stops at the last.
PRICE_STEPS: Final = (3, 4, 5)
STOP_STEP: Final = 5
# Under this many usual prices a rise is over.
EASE_UNDER: Final = 2
# Results before a price means anything: one morning lead is a coin toss.
# Fewer are judged only once this many usual prices are gone.
MIN_PRICE_RESULTS: Final = 3
FEW_RESULTS_SPEND: Final = 10
# Usual prices gone with nothing back before a group not ours - or one we may
# not stop - is warned about. Ours is stopped at three: a stop is ours to
# make; a warning only asks for a look, and asks too often at three.
FRUITLESS_WARN_TIMES: Final = 5
# Hours after the switch-on before anything but a broken page is judged.
WAIT_HOURS: Final = 24
# Results before a new group's first days have a price of their own.
START_RESULTS: Final = 3
# Hours after the switch-on before a group that never brought a result is
# stopped. Before that, a day's budget gone with nothing back is a warning.
NEVER_STOP_HOURS: Final = 72
# ``now / usual`` in percent: the click rate's floor, the showings' ceiling.
CTR_LOW_PCT: Final = 70
CPM_HIGH_PCT: Final = 150
CONVERSION_LOW_PCT: Final = 70
# A rate is said only once the price is this far up, in percent of usual.
RATE_PRICE_PCT: Final = 150
# Showings before a rate of today's means anything.
MIN_RATE_IMPRESSIONS: Final = 1_000
# Frequency over seven days, in hundredths.
FREQUENCY_BAR: Final = 300
# An advert's share of its group's money before it is called the weak one.
WEAK_AD_SHARE_PCT: Final = 30
# What a budget is lowered by when that is the advice.
BUDGET_STEP_PCT: Final = 20


@dataclass(frozen=True, slots=True)
class Usual:
    """The one usual level a group is held against.

    The group's own last fortnight where it has one; else the pooled price
    of its own first days, once they brought :data:`START_RESULTS` results -
    a price only, and one nothing is stopped for rising past. ``None`` where
    the group has no price yet: it is then held against its day's budget.
    """

    cost_minor: int | None = None
    link_ctr_bp: int | None = None
    cpm_minor: int | None = None
    source: Source | None = None


@dataclass(frozen=True, slots=True)
class AdToday:
    """One advert of the group, today."""

    ad_id: str
    name: str = ""
    spend_minor: int = 0
    results: int = 0
    live: bool = True


@dataclass(frozen=True, slots=True)
class GroupToday:
    """One running group's day so far, and what it is held against.

    ``hours_running`` is since it was switched on; ``None`` where that is
    not known, which is read as long ago. ``frequency`` is the provider's
    seven-day one, in hundredths. ``own_budget`` is whether the group has a
    day's budget of its own to lower.
    """

    adset_id: str
    spend_minor: int = 0
    results: int = 0
    impressions: int = 0
    link_clicks: int = 0
    ours: bool = False
    hours_running: float | None = None
    learning: bool = False
    site_down: bool = False
    own_budget: bool = False
    frequency: int | None = None
    usual: Usual = field(default_factory=Usual)
    ads: tuple[AdToday, ...] = ()
    # The money gone since the last result, today's included, over at most
    # a week - and how many days that is. A small budget never spends three
    # usual prices in one day, and is no less fruitless for it.
    dry_spend_minor: int = 0
    dry_days: int = 1
    # The day's budget, its own or its campaign's; ``0`` where it has none.
    day_budget_minor: int = 0
    # Results on its finished days since the switch-on, a fortnight at most.
    past_results: int = 0


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing to tell the owner about a group or one of its adverts.

    ``step`` orders a kind's messages: a finding is said again only at a
    higher step than the one already said. ``times`` is the price in usual
    prices, in hundredths; ``0`` where the finding has no price.
    """

    kind: Kind
    action: Action
    advice: Advice
    adset_id: str
    ad_id: str = ""
    step: int = 1
    times: int = 0
    causes: tuple[Cause, ...] = ()


def too_young(group: GroupToday) -> bool:
    return group.hours_running is not None and group.hours_running < WAIT_HOURS


def price_times(group: GroupToday) -> int:
    """Today's price in usual prices, in hundredths; ``0`` where it has none."""
    usual = group.usual.cost_minor
    if not usual or group.results <= 0:
        return 0
    return group.spend_minor * 100 // (usual * group.results)


def price_step(times: int) -> int:
    """The highest step this price has reached, or ``0`` under the first."""
    reached = [step for step in PRICE_STEPS if times >= step * 100]
    return max(reached, default=0)


def eased(group: GroupToday) -> bool:
    """A rise is over: results today at under two usual prices each, with a
    usual price's worth spent - a morning's first cheap result is not it."""
    usual = group.usual.cost_minor
    if not usual or group.results <= 0 or group.spend_minor < usual:
        return False
    return group.spend_minor < EASE_UNDER * usual * group.results


def causes(group: GroupToday) -> tuple[Cause, ...]:
    """Why the price is what it is, by the funnel's three steps.

    One result costs ``CPM ÷ (1000 × CTR × conversion)``, so a rise is in
    one of the three; each is named when it is past its bar against usual.
    The conversion's usual level is the one the other two imply.
    """
    usual = group.usual
    found: list[Cause] = []
    cpm = formulas.cpm(group.spend_minor, group.impressions)
    if (
        cpm is not None
        and usual.cpm_minor
        and cpm * 100 >= usual.cpm_minor * CPM_HIGH_PCT
    ):
        found.append("cpm")
    measured = group.impressions >= MIN_RATE_IMPRESSIONS
    if measured and usual.link_ctr_bp:
        ctr_bp = basis_points_or_none(
            formulas.ctr(group.link_clicks, group.impressions)
        )
        if ctr_bp is not None and ctr_bp * 100 <= usual.link_ctr_bp * CTR_LOW_PCT:
            found.append("ctr")
    if _conversion_fell(group):
        found.append("conversion")
    return tuple(found)


def _conversion_fell(group: GroupToday) -> bool:
    """Results per link click against the level the usual figures imply."""
    usual = group.usual
    if not (usual.cost_minor and usual.cpm_minor and usual.link_ctr_bp):
        return False
    if group.link_clicks <= 0:
        return False
    # usual clicks for one result = usual cost ÷ usual cost per click, and
    # the usual cost per click = usual CPM ÷ (1000 × usual CTR).
    usual_clicks_per_result = (
        usual.cost_minor * usual.link_ctr_bp / (usual.cpm_minor * 10)
    )
    if usual_clicks_per_result <= 0:
        return False
    now_clicks_per_result = group.link_clicks / max(group.results, 1)
    # Conversion is the inverse: fallen to 70 % is clicks per result at 1/0.7.
    return now_clicks_per_result * CONVERSION_LOW_PCT >= usual_clicks_per_result * 100


def judge(group: GroupToday) -> list[Finding]:
    """Everything today's figures say about one running group."""
    if group.site_down:
        return [
            Finding(
                kind="site_down",
                action=_stop_or_warn(group),
                advice="keep_off" if group.ours else "pause",
                adset_id=group.adset_id,
            )
        ]
    if too_young(group):
        return []
    money = _money(group) if group.usual.cost_minor else _unpriced(group)
    if money is not None:
        return [money]
    return [*_weak_ads(group), *_rates(group)]


def _stop_or_warn(group: GroupToday) -> Action:
    return "stop" if group.ours else "warn"


def _unpriced(group: GroupToday) -> Finding | None:
    """A group with no price of its own yet, held against its day's budget.

    A day's budget gone since the last result with nothing back is a
    warning. One that never brought a result is stopped once it has run
    :data:`NEVER_STOP_HOURS` - step two of the same finding, so the warning
    comes first where the money went first. A group with no day's budget is
    held to having spent at all: the first day's wait has passed by then.
    """
    if group.results > 0:
        return None
    gone = max(group.spend_minor, group.dry_spend_minor)
    if gone <= 0 or gone < group.day_budget_minor:
        return None
    old = group.hours_running is None or group.hours_running >= NEVER_STOP_HOURS
    if group.ours and group.past_results <= 0 and old:
        return Finding(
            kind="fruitless",
            action="stop",
            advice="keep_off",
            adset_id=group.adset_id,
            step=2,
            causes=causes(group),
        )
    return Finding(
        kind="fruitless",
        action="warn",
        advice="pause",
        adset_id=group.adset_id,
        causes=causes(group),
    )


def _money(group: GroupToday) -> Finding | None:
    """Nothing back for three usual prices, or a result at three and more."""
    usual = group.usual.cost_minor
    if not usual:
        return None
    if group.results <= 0:
        gone = max(group.spend_minor, group.dry_spend_minor)
        action = _stop_or_warn(group)
        bar = SPEND_MULTIPLE if action == "stop" else FRUITLESS_WARN_TIMES
        if gone < bar * usual:
            return None
        return Finding(
            kind="fruitless",
            action=action,
            advice="keep_off" if action == "stop" else "pause",
            adset_id=group.adset_id,
            times=gone * 100 // usual,
            causes=causes(group),
        )
    if (
        group.results < MIN_PRICE_RESULTS
        and group.spend_minor < FEW_RESULTS_SPEND * usual
    ):
        return None
    times = price_times(group)
    step = price_step(times)
    if not step:
        return None
    why = causes(group)
    settled = group.usual.source != "start"
    if step >= STOP_STEP and group.ours and not group.learning and settled:
        return Finding(
            kind="price",
            action="stop",
            advice="keep_off",
            adset_id=group.adset_id,
            step=step,
            times=times,
            causes=why,
        )
    return Finding(
        kind="price",
        action="warn",
        advice=_price_advice(group, step=step, why=why),
        adset_id=group.adset_id,
        step=step,
        times=times,
        causes=why,
    )


def _price_advice(group: GroupToday, *, step: int, why: tuple[Cause, ...]) -> Advice:
    """Which button a price warning advises.

    Learning is left alone; past four usual prices the stop is next, so it
    is advised now; a rise that is only the showings' price is the auction
    and usually passes; one in the click rate or the conversion is the
    advert or the form wearing out, and less money goes to it meanwhile.
    """
    if group.learning:
        return "leave"
    if step >= 4:
        return "pause"
    if why == ("cpm",) or not why:
        return "leave"
    return "budget_down" if group.own_budget else "leave"


def _weak_ads(group: GroupToday) -> list[Finding]:
    """An advert with a third of the money and nothing back, beside one that
    brings results. Never the last advert, and only ever a warning."""
    usual = group.usual.cost_minor
    spending = [ad for ad in group.ads if ad.live and ad.spend_minor > 0]
    if not usual or len(spending) < 2 or not any(ad.results > 0 for ad in spending):
        return []
    total = sum(ad.spend_minor for ad in spending)
    return [
        Finding(
            kind="weak_ad",
            action="warn",
            advice="pause_ad",
            adset_id=group.adset_id,
            ad_id=ad.ad_id,
            times=ad.spend_minor * 100 // usual,
        )
        for ad in spending
        if ad.results <= 0
        and ad.spend_minor >= SPEND_MULTIPLE * usual
        and ad.spend_minor * 100 >= total * WEAK_AD_SHARE_PCT
    ]


def _rates(group: GroupToday) -> list[Finding]:
    """The click rate, the showings' price and the frequency - at most one,
    the first of them, since each asks for the same look at the advert.

    A rate is said only while the price is already going up with it. On any
    one day a tenth of all groups sit under 70 % of their usual click rate
    and cost what they always cost; that is a day, not a problem.
    """
    if group.frequency is not None and group.frequency >= FREQUENCY_BAR:
        return [_rate(group, "frequency", "add_creative")]
    if not _price_is_climbing(group):
        return []
    why = causes(group)
    if "ctr" in why:
        return [_rate(group, "ctr", "add_creative")]
    if "cpm" in why and group.impressions >= MIN_RATE_IMPRESSIONS:
        return [_rate(group, "cpm", "leave")]
    return []


def _price_is_climbing(group: GroupToday) -> bool:
    """One and a half usual prices for a result - or a usual price's worth
    gone with none yet. Under three, where the price has its own message."""
    usual = group.usual.cost_minor
    if not usual:
        return False
    if group.results <= 0:
        return group.spend_minor >= usual
    return price_times(group) >= RATE_PRICE_PCT


def _rate(group: GroupToday, kind: Kind, advice: Advice) -> Finding:
    return Finding(kind=kind, action="warn", advice=advice, adset_id=group.adset_id)


__all__ = [
    "BUDGET_STEP_PCT",
    "CPM_HIGH_PCT",
    "CTR_LOW_PCT",
    "EASE_UNDER",
    "FEW_RESULTS_SPEND",
    "FREQUENCY_BAR",
    "FRUITLESS_WARN_TIMES",
    "MIN_PRICE_RESULTS",
    "NEVER_STOP_HOURS",
    "PRICE_STEPS",
    "START_RESULTS",
    "STOP_STEP",
    "WAIT_HOURS",
    "WEAK_AD_SHARE_PCT",
    "Action",
    "AdToday",
    "Advice",
    "Cause",
    "Finding",
    "GroupToday",
    "Kind",
    "Usual",
    "causes",
    "eased",
    "judge",
    "price_step",
    "price_times",
    "too_young",
]
