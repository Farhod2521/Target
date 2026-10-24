"""The separate things a diagnosis notices about one group."""

from typing import Final, Literal, get_args

from core.agent.benchmark import Benchmark, lead_count, result_count
from core.agent.contracts import Policy
from core.agent.facts import AdFacts, AdSetFacts, troubled
from core.agent.funnel import per_ten_thousand
from core.agent.rules.audience import (
    FREQUENCY_RISE_PCT,
    MIN_HALF_DAYS,
    MIN_HALF_IMPRESSIONS,
    MIN_WORN_FREQUENCY,
)

Signal = Literal[
    "provider_issue",
    "site_down",
    "learning_stuck",
    "learning",
    "few_days",
    "few_impressions",
    "underspending",
    "worn_out",
    "fatigued",
    "low_ranking",
    "low_ctr",
    "weak_hook",
    "weak_hold",
    "high_cpm",
    "quality_below_engagement",
    "low_click_to_lead",
    "low_arrival",
    "conversion_ranking_low",
    "junk_numbers",
    "long_form",
    "learning_limited",
]
SIGNALS: Final[tuple[Signal, ...]] = get_args(Signal)

FACTS: Final[frozenset[Signal]] = frozenset(
    {
        "provider_issue",
        "site_down",
        "learning_stuck",
        "learning",
        "few_days",
        "few_impressions",
    }
)

MIN_IMPRESSIONS: Final = 500
MIN_RATE_IMPRESSIONS: Final = 1_000
LOW_RATE_SHARE_PCT: Final = 70
HOOK_FLOOR_BP: Final = 2_000
HOLD_FLOOR_BP: Final = 1_000
LEARNING_RESULTS: Final = 50
STUCK_SHARE_PCT: Final = 30
FATIGUE_SHARE_PCT: Final = 70
JUNK_SHARE_PCT: Final = 10
JUNK_MIN_LEADS: Final = 10
UNDERSPEND_SHARE_PCT: Final = 70
HIGH_CPM_SHARE_PCT: Final = 150
MIN_CLICKS: Final = 100
LOW_CONVERSION_SHARE_PCT: Final = 50
LOW_ARRIVAL_BP: Final = 5_000
MAX_EASY_QUESTIONS: Final = 4

BOTTOM: Final[frozenset[str]] = frozenset({"below_average_20", "below_average_10"})
BELOW: Final[frozenset[str]] = BOTTOM | {"below_average_35"}
FINE: Final[frozenset[str]] = frozenset({"average", "above_average"})


def signals(
    *, item: AdSetFacts, bench: Benchmark, policy: Policy
) -> tuple[Signal, ...]:
    """Everything noticed about one group, in funnel order."""
    found = {
        *_facts(item, policy),
        *_delivery(item),
        *_attention(item, bench, policy),
        *_standing(item, policy),
        *_after_click(item, bench),
    }
    return tuple(signal for signal in SIGNALS if signal in found)


def leading_ads(item: AdSetFacts, policy: Policy) -> tuple[AdFacts, ...]:
    """The delivering adverts carrying a real share of the group's money."""
    spend = item.totals.spend_minor
    if spend <= 0:
        return ()
    return tuple(
        ad
        for ad in item.ads
        if ad.is_active
        and ad.in_window
        and ad.figures.spend_minor * 100 >= spend * policy.dead_segment_share_pct
    )


def _facts(item: AdSetFacts, policy: Policy) -> list[Signal]:
    found: list[Signal] = []
    if troubled(item):
        found.append("provider_issue")
    if item.landing.down_urls:
        found.append("site_down")
    if item.is_learning:
        found.append("learning_stuck" if _stuck(item, policy) else "learning")
    if item.days_with_spend < policy.min_days:
        found.append("few_days")
    if item.funnel.impressions < MIN_IMPRESSIONS:
        found.append("few_impressions")
    if item.learning_limited:
        found.append("learning_limited")
    return found


def _stuck(item: AdSetFacts, policy: Policy) -> bool:
    """A full window of learning with too few results to ever finish it."""
    if item.days_with_spend < policy.window_days:
        return False
    count = result_count(item)
    return count is not None and count * 100 < LEARNING_RESULTS * STUCK_SHARE_PCT


def _delivery(item: AdSetFacts) -> list[Signal]:
    """Whether the group spends what it is allowed to."""
    if not item.daily_budget_minor or item.budget_moved:
        return []
    share = item.spend_share
    return ["underspending"] if 0 < share < UNDERSPEND_SHARE_PCT else []


def _attention(item: AdSetFacts, bench: Benchmark, policy: Policy) -> list[Signal]:
    own = item.funnel
    found: list[Signal] = []
    if _worn_out(item, policy):
        found.append("worn_out")
    if _fatigued(item, policy):
        found.append("fatigued")
    if own.impressions < MIN_RATE_IMPRESSIONS:
        return found
    if _below(own.link_ctr_bp, bench.funnel.link_ctr_bp, LOW_RATE_SHARE_PCT):
        found.append("low_ctr")
    if _weak(own.hook_bp, bench.hook_bp, HOOK_FLOOR_BP):
        found.append("weak_hook")
    if _weak(own.hold_bp, bench.hold_bp, HOLD_FLOOR_BP):
        found.append("weak_hold")
    if _at_least(own.cpm_minor, bench.funnel.cpm_minor, HIGH_CPM_SHARE_PCT):
        found.append("high_cpm")
    return found


def _fatigued(item: AdSetFacts, policy: Policy) -> bool:
    """The last three days clicked far less than the first three ever did."""
    if item.days_with_spend < policy.window_days:
        return False
    if item.recent.totals.impressions < MIN_RATE_IMPRESSIONS:
        return False
    return _below(item.recent.link_ctr_bp, item.launch_ctr_bp, FATIGUE_SHARE_PCT)


def _weak(own: int | None, peers: int | None, floor: int) -> bool:
    """Under the comparable groups' rate, or under the floor without them."""
    if peers is not None:
        return _below(own, peers, LOW_RATE_SHARE_PCT)
    return own is not None and own < floor


def _worn_out(item: AdSetFacts, policy: Policy) -> bool:
    """The same people keep seeing it and have stopped clicking."""
    early, late = item.early, item.late
    if min(early.days, late.days) < MIN_HALF_DAYS:
        return False
    if min(early.impressions, late.impressions) < MIN_HALF_IMPRESSIONS:
        return False
    before, after = early.link_ctr_bp, late.link_ctr_bp
    if before is None or after is None or before <= 0:
        return False
    if (before - after) * 100 < before * policy.ctr_drop_pct:
        return False
    if late.frequency < MIN_WORN_FREQUENCY:
        return False
    return late.frequency * 100 > early.frequency * (100 + FREQUENCY_RISE_PCT)


def _standing(item: AdSetFacts, policy: Policy) -> list[Signal]:
    """What the provider says about the adverts carrying the money."""
    found: list[Signal] = []
    for ad in leading_ads(item, policy):
        quality, engagement = ad.quality_ranking, ad.engagement_ranking
        if engagement in BOTTOM or (quality in BOTTOM and engagement not in FINE):
            found.append("low_ranking")
        if quality in BELOW and engagement in FINE:
            found.append("quality_below_engagement")
        if ad.conversion_ranking in BOTTOM and engagement in FINE:
            found.append("conversion_ranking_low")
    return found


def _after_click(item: AdSetFacts, bench: Benchmark) -> list[Signal]:
    own = item.funnel
    found: list[Signal] = []
    if item.counts_leads and _form_stalls(item, bench):
        found.append("low_click_to_lead")
    if (
        item.landing.pixel_seen
        and own.link_clicks >= MIN_CLICKS
        and _below(own.arrival_bp, LOW_ARRIVAL_BP, 100)
    ):
        found.append("low_arrival")
    if item.counts_leads and _junk(item):
        found.append("junk_numbers")
    if item.landing.form_questions > MAX_EASY_QUESTIONS:
        found.append("long_form")
    return found


def _junk(item: AdSetFacts) -> bool:
    leads = lead_count(item)
    return leads >= JUNK_MIN_LEADS and item.junk_leads * 100 > leads * JUNK_SHARE_PCT


def _form_stalls(item: AdSetFacts, bench: Benchmark) -> bool:
    """Enough people clicked, and too few of them became a lead."""
    clicks = item.funnel.link_clicks
    if clicks < MIN_CLICKS:
        return False
    leads = lead_count(item)
    if leads == 0:
        return True
    own = per_ten_thousand(part=leads, whole=clicks)
    return _below(own, bench.click_to_lead_bp, LOW_CONVERSION_SHARE_PCT)


def _below(value: int | None, base: int | None, share_pct: int) -> bool:
    """``value`` is under ``share_pct`` percent of ``base``."""
    if value is None or base is None or base <= 0:
        return False
    return value * 100 < base * share_pct


def _at_least(value: int | None, base: int | None, share_pct: int) -> bool:
    """``value`` is at ``share_pct`` percent of ``base`` or over."""
    if value is None or base is None or base <= 0:
        return False
    return value * 100 >= base * share_pct


__all__ = [
    "BELOW",
    "BOTTOM",
    "FACTS",
    "FINE",
    "HIGH_CPM_SHARE_PCT",
    "LOW_ARRIVAL_BP",
    "LOW_CONVERSION_SHARE_PCT",
    "LOW_RATE_SHARE_PCT",
    "MAX_EASY_QUESTIONS",
    "MIN_CLICKS",
    "MIN_IMPRESSIONS",
    "MIN_RATE_IMPRESSIONS",
    "SIGNALS",
    "Signal",
    "leading_ads",
    "signals",
]
