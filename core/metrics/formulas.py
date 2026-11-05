"""Each metric's formula, once, on plain numbers.

The catalogue's metrics are built from these, and so is every older screen,
report and rule that holds its counts in a shape of its own. A rate comes
back exact; whoever shows it rounds it with :mod:`core.metrics.arithmetic`.
"""

from decimal import Decimal
from typing import Final

from adskit import MinorUnits

from core.metrics.arithmetic import cost_per, exact_percent, exact_ratio
from core.metrics.outcomes import Outcome

PER_MILLE: Final = 1000

# What one result is counted in, and per how many of them its cost is
# quoted. A reach campaign's result is a thousand showings, as in Ads
# Manager; everything else is priced per one.
RESULT_OF: Final[dict[Outcome, tuple[str, int]]] = {
    "lead": ("leads", 1),
    "site_lead": ("leads_reported", 1),
    "chat": ("results", 1),
    "call": ("results", 1),
    "click": ("results", 1),
    "view": ("impressions", PER_MILLE),
    "recall": ("recallers", 1),
    "profile": ("profile_visits", 1),
}


def result_per(outcome: Outcome) -> int:
    """How many results one quoted cost is for."""
    found = RESULT_OF.get(outcome)
    return found[1] if found else 1


# -- costs -----------------------------------------------------------------------------


def cost_per_result(
    spend_minor: int, results: int, *, per: int = 1
) -> MinorUnits | None:
    """Spend over results, per ``per`` of them."""
    return cost_per(MinorUnits(spend_minor * per), results)


def cpl(spend_minor: int, leads: int) -> MinorUnits | None:
    return cost_per(MinorUnits(spend_minor), leads)


def cpql(spend_minor: int, qualified: int) -> MinorUnits | None:
    return cost_per(MinorUnits(spend_minor), qualified)


def cpm(spend_minor: int, impressions: int) -> MinorUnits | None:
    return cost_per(MinorUnits(spend_minor * PER_MILLE), impressions)


def cpc(spend_minor: int, clicks: int) -> MinorUnits | None:
    """Spend over clicks: link clicks for the expert's CPC, every click for
    the older panel's."""
    return cost_per(MinorUnits(spend_minor), clicks)


def cost_per_purchase(spend_minor: int, purchases: int) -> MinorUnits | None:
    return cost_per(MinorUnits(spend_minor), purchases)


# -- rates -----------------------------------------------------------------------------


def ctr(clicks: int, impressions: int) -> Decimal | None:
    """Clicks per hundred impressions: link clicks for the expert's CTR,
    every click for the older panel's."""
    return exact_percent(part=clicks, whole=impressions)


def unique_ctr(unique_clicks: int, reach: int) -> Decimal | None:
    return exact_percent(part=unique_clicks, whole=reach)


def click_quality(unique_clicks: int, clicks: int) -> Decimal | None:
    """What share of the clicks came from different people."""
    return exact_percent(part=unique_clicks, whole=clicks)


def frequency(impressions: int, reach: int) -> Decimal | None:
    return exact_ratio(part=impressions, whole=reach)


def hook_rate(views_3s: int, impressions: int) -> Decimal | None:
    return exact_percent(part=views_3s, whole=impressions)


def hold_rate(thruplays: int, views_3s: int) -> Decimal | None:
    return exact_percent(part=thruplays, whole=views_3s)


def thruplay_share(thruplays: int, plays: int) -> Decimal | None:
    """What share of the people who started the video watched it through."""
    return exact_percent(part=thruplays, whole=plays)


def completion_rate(p100: int, plays: int) -> Decimal | None:
    return exact_percent(part=p100, whole=plays)


def arrival_rate(landing_page_views: int, link_clicks: int) -> Decimal | None:
    """What share of the link clicks reached a page that finished loading."""
    return exact_percent(part=landing_page_views, whole=link_clicks)


def qualified_share(qualified: int, leads: int) -> Decimal | None:
    return exact_percent(part=qualified, whole=leads)


def lead_share(part: int, leads: int) -> Decimal | None:
    """What share of the leads a CRM count is: the marked, the qualified, the junk."""
    return exact_percent(part=part, whole=leads)


def spend_share(part_minor: int, whole_minor: int) -> Decimal | None:
    """What share of the money one part of it took."""
    return exact_percent(part=part_minor, whole=whole_minor)


def form_conversion(leads: int, step_before: int) -> Decimal | None:
    """Leads over the clicks of an instant form or the page views of a site."""
    return exact_percent(part=leads, whole=step_before)


def step_rate(passed: int, entered: int) -> Decimal | None:
    """What share of the people at one step of the funnel reached the next."""
    return exact_percent(part=passed, whole=entered)


def cost_index(cost_minor: int, average_minor: int) -> Decimal | None:
    """A cost against the average of its kind, the average being a hundred."""
    return exact_percent(part=cost_minor, whole=average_minor)


def roas(value_minor: int, spend_minor: int) -> Decimal | None:
    return exact_ratio(part=value_minor, whole=spend_minor)


__all__ = [
    "PER_MILLE",
    "RESULT_OF",
    "arrival_rate",
    "click_quality",
    "completion_rate",
    "cost_index",
    "cost_per_purchase",
    "cost_per_result",
    "cpc",
    "cpl",
    "cpm",
    "cpql",
    "ctr",
    "form_conversion",
    "frequency",
    "hold_rate",
    "hook_rate",
    "lead_share",
    "qualified_share",
    "result_per",
    "roas",
    "spend_share",
    "step_rate",
    "thruplay_share",
    "unique_ctr",
]
