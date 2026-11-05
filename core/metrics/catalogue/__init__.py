"""Every metric a screen, a report or a rule may ask for, computed in one place.

Ask :func:`compute` for a key with the range's :class:`Figures` and the
:class:`Setting` it belongs to; the answer is the value or the reason there
is none. Nothing outside this package divides one figure by another.

The common metrics hold for every network. A network's own metrics are in
its module and exist only on it.
"""

from collections.abc import Iterable
from typing import Final

from core.metrics.catalogue.common import COMMON, leads, result_count, sales
from core.metrics.catalogue.meta import META, RANKED_FROM
from core.metrics.catalogue.spec import (
    AD_ONLY,
    ALL_LEVELS,
    ALL_NETWORKS,
    META_ONLY,
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


def metrics_for(*, level: Level, network: Network) -> tuple[Metric, ...]:
    """The metrics that exist at this level on this network, in column order."""
    setting = Setting(level=level, network=network)
    return tuple(metric for metric in CATALOGUE if metric.exists(setting))


def compute(key: str, figures: Figures, setting: Setting) -> Answer:
    """One metric for one range of one object."""
    metric = BY_KEY[key]
    if not metric.exists(setting):
        return missing("not_here")
    if metric.from_network and not figures.read:
        return missing("not_read")
    return metric.formula(figures, setting)


def compute_many(
    keys: Iterable[str], figures: Figures, setting: Setting
) -> dict[str, Answer]:
    return {key: compute(key, figures, setting) for key in keys}


__all__ = [
    "AD_ONLY",
    "ALL_LEVELS",
    "ALL_NETWORKS",
    "BY_KEY",
    "CATALOGUE",
    "META_ONLY",
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
    "compute",
    "compute_many",
    "leads",
    "metrics_for",
    "result_count",
    "sales",
]
