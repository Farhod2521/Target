"""The grouped reads the campaign look-ups are built from."""

from collections.abc import Mapping
from datetime import date
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.models import AdSet, Campaign
from app.modules.chat.selectors.lookups.common import figure_sums
from app.modules.chat.selectors.scope import lead_window
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.results import screen_kind
from core.metrics import Outcome, campaign_goal

_LEVEL_OF: Final[dict[str, str]] = {
    "campaign_external_id": MetricLevel.ADSET,
    "adset_external_id": MetricLevel.ADSET,
    "ad_external_id": MetricLevel.AD,
}


def _counter(column: str) -> Any:
    from app.modules.leads.selectors import (
        counts_by_ad,
        counts_by_adset,
        counts_by_campaign,
    )

    return {
        "campaign_external_id": counts_by_campaign,
        "adset_external_id": counts_by_adset,
        "ad_external_id": counts_by_ad,
    }.get(column)


def spenders_by(
    db: Session, *, owner: User, column: str, since: date, until: date
) -> set[str]:
    """The ids that spent anything over the window."""
    field = getattr(MetricsDaily, column)
    rows = db.scalars(
        select(field)
        .where(
            MetricsDaily.owner_id == owner.id,
            MetricsDaily.level == _LEVEL_OF[column],
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
            MetricsDaily.spend_minor > 0,
            field != "",
        )
        .distinct()
    )
    return {str(value) for value in rows}


def figures_by(
    db: Session, *, owner: User, column: str, ids: list[str], since: date, until: date
) -> dict[str, Mapping[str, Any]]:
    """``{id: summed figures}`` over the window."""
    if not ids:
        return {}
    field = getattr(MetricsDaily, column)
    rows = db.execute(
        select(field.label("key"), *figure_sums())
        .where(
            MetricsDaily.owner_id == owner.id,
            MetricsDaily.level == _LEVEL_OF[column],
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
            field.in_(ids),
        )
        .group_by(field)
    ).mappings()
    return {str(row["key"]): row for row in rows}


def leads_by(
    db: Session, *, owner: User, column: str, ids: list[str], since: date, until: date
) -> dict[str, int]:
    """``{id: leads received}`` over the window. Counted, never read."""
    if not ids:
        return {}
    counter = _counter(column)
    if counter is None:
        return {}
    start, end = lead_window(db, owner=owner, since=since, until=until)
    wanted = set(ids)
    counted = counter(db, owner=owner, since=start, until=end)
    return {key: pair[0] for key, pair in counted.items() if key in wanted}


def kinds_by_campaign(
    db: Session, *, owner: User, ids: list[str]
) -> dict[str, Outcome]:
    """What each campaign was bought for, as the screens read it."""
    if not ids:
        return {}
    grouped: dict[str, list[tuple[str, str, Mapping[str, Any] | None]]] = {}
    rows = db.execute(
        select(
            Campaign.external_id,
            AdSet.external_id,
            AdSet.optimization_goal_raw,
            AdSet.promoted_object_raw,
        )
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(AdSet.owner_id == owner.id, Campaign.external_id.in_(ids))
    )
    for campaign_id, external_id, goal, promoted in rows:
        grouped.setdefault(str(campaign_id), []).append(
            (
                external_id,
                goal or "",
                promoted if isinstance(promoted, Mapping) else None,
            )
        )
    return {
        campaign_id: screen_kind(*campaign_goal(adsets))
        for campaign_id, adsets in grouped.items()
    }


def group_budgets(db: Session, *, owner: User, ids: list[str]) -> dict[str, int]:
    """``{campaign id: its groups' daily budgets added}``."""
    if not ids:
        return {}
    rows = db.execute(
        select(Campaign.external_id, func.sum(AdSet.daily_budget_minor))
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(AdSet.owner_id == owner.id, Campaign.external_id.in_(ids))
        .group_by(Campaign.external_id)
    )
    return {str(key): int(total or 0) for key, total in rows}


__all__ = [
    "figures_by",
    "group_budgets",
    "kinds_by_campaign",
    "leads_by",
    "spenders_by",
]
