"""Every metric a screen, a report or a rule may ask for, computed in one place.

Ask :func:`compute` for a key with the range's :class:`Figures` and the
:class:`Setting` it belongs to; the answer is the value or the reason there
is none. Nothing outside this package divides one figure by another.

The common metrics hold for every network. A network's own metrics are in
its module and exist only on it.
"""

from collections.abc import Iterable, Sequence
from dataclasses import fields, replace
from typing import Any, Final

from adskit import MinorUnits

from core.metrics.catalogue.common import COMMON, leads, result_count, sales
from core.metrics.catalogue.meta import META, RANKED_FROM
from core.metrics.catalogue.spec import (
    AD_ONLY,
    ALL_LEVELS,
    ALL_NETWORKS,
    META_ONLY,
    MISSING_WORDS,
    Answer,
    Figures,
    Group,
    Level,
    Metric,
    Missing,
    Network,
    Setting,
    Unit,
    Value,
    missing,
)

BY_KEY: Final[dict[str, Metric]] = {metric.key: metric for metric in (*COMMON, *META)}

# The order the columns stand in, as the expert's table reads them.
ORDER: Final[tuple[str, ...]] = (
    "spend",
    "results",
    "cost_per_result",
    "reach",
    "impressions",
    "frequency",
    "cpm",
    "hook_rate",
    "hold_rate",
    "link_clicks",
    "unique_link_clicks",
    "ctr",
    "cpc",
    "quality_ranking",
    "engagement_rate_ranking",
    "conversion_rate_ranking",
    "leads",
    "form_conversion",
    "qualified",
    "qualified_share",
    "cpql",
    "purchases_site",
    "purchases_crm",
    "cost_per_purchase",
    "purchase_value",
    "roas",
)

CATALOGUE: Final[tuple[Metric, ...]] = tuple(BY_KEY[key] for key in ORDER)


# The counts a total adds up. People (reach, unique clicks) and the rankings
# are not among them: two rows can hold the same person, and a ranking is one
# advert's.
ADDED: Final[tuple[str, ...]] = tuple(
    one.name
    for one in fields(Figures)
    if one.name
    not in {
        "reach",
        "unique_link_clicks",
        "quality_ranking",
        "engagement_rate_ranking",
        "conversion_rate_ranking",
        "read",
        "crm",
        "mixed_currency",
    }
)


def add_up(
    rows: Sequence[Figures],
    *,
    currencies: int = 1,
    reach: int | None = None,
    unique_link_clicks: int | None = None,
) -> Figures:
    """The total row: counts summed, people only where one row stands alone
    or the network counted the rows' people together - ``reach`` and
    ``unique_link_clicks``, which never come from adding the rows' own.

    Its rates are then computed from these sums like any row's, never as the
    mean of the rows' rates.
    """
    if len(rows) == 1:
        return replace(rows[0], mixed_currency=currencies > 1)
    summed: dict[str, Any] = {
        name: sum(int(getattr(row, name)) for row in rows) for name in ADDED
    }
    summed["spend_minor"] = MinorUnits(summed["spend_minor"])
    summed["purchase_value_site_minor"] = MinorUnits(
        summed["purchase_value_site_minor"]
    )
    shown = int(summed["impressions"])
    return Figures(
        **summed,
        reach=_counted(reach, shown=shown),
        unique_link_clicks=_counted(unique_link_clicks, shown=shown),
        read=bool(rows) and all(row.read for row in rows),
        crm=any(row.crm for row in rows),
        mixed_currency=currencies > 1,
    )


def _counted(people: int | None, *, shown: int) -> int | None:
    """More people than showings is a count of some other rows."""
    if people is None or people > shown:
        return None
    return people


def metrics_for(*, level: Level, network: Network) -> tuple[Metric, ...]:
    """The metrics that exist at this level on this network, in column order."""
    setting = Setting(level=level, network=network)
    return tuple(metric for metric in CATALOGUE if metric.exists(setting))


def compute(key: str, figures: Figures, setting: Setting) -> Answer:
    """One metric for one range of one object."""
    metric = BY_KEY[key]
    if not metric.exists(setting):
        return missing("not_here")
    if setting.mixed and metric.by_goal:
        return missing("mixed_goals")
    if figures.mixed_currency and (metric.unit == "money" or metric.key == "roas"):
        return missing("mixed_currency")
    if metric.from_crm and not figures.crm:
        return missing("no_crm")
    if metric.from_network and not figures.read:
        return missing("not_read")
    return metric.formula(figures, setting)


def compute_many(
    keys: Iterable[str], figures: Figures, setting: Setting
) -> dict[str, Answer]:
    return {key: compute(key, figures, setting) for key in keys}


__all__ = [
    "ADDED",
    "AD_ONLY",
    "ALL_LEVELS",
    "ALL_NETWORKS",
    "BY_KEY",
    "CATALOGUE",
    "META_ONLY",
    "MISSING_WORDS",
    "ORDER",
    "RANKED_FROM",
    "Answer",
    "Figures",
    "Group",
    "Level",
    "Metric",
    "Missing",
    "Network",
    "Setting",
    "Unit",
    "Value",
    "add_up",
    "compute",
    "compute_many",
    "leads",
    "metrics_for",
    "result_count",
    "sales",
]
