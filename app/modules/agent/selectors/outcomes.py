"""What the days since one change added up to."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.agent.selectors.window import end_of, start_of, yesterday
from app.modules.metrics.constants import EVERY_ACCOUNT, MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.facts import cabinet_where
from core.agent import Aftermath
from core.metrics import Totals

Counts = Callable[..., dict[str, tuple[int, int]]]
_ID_COLUMNS: Final[dict[str, str]] = {
    MetricLevel.CAMPAIGN: "campaign_external_id",
    MetricLevel.ADSET: "adset_external_id",
    MetricLevel.AD: "ad_external_id",
}


def _lead_counts(level: str) -> Counts:
    from app.modules.leads.selectors import (
        counts_by_ad,
        counts_by_adset,
        counts_by_campaign,
    )

    return {
        MetricLevel.CAMPAIGN: counts_by_campaign,
        MetricLevel.ADSET: counts_by_adset,
        MetricLevel.AD: counts_by_ad,
    }[level]


def after_figures(
    db: Session,
    *,
    owner: User,
    level: str,
    external_id: str,
    changed_at: datetime,
    tzinfo: ZoneInfo,
    now: datetime,
) -> Aftermath:
    """One object's figures since a change, as the verdict takes them."""
    first = changed_at.astimezone(tzinfo).date() + timedelta(days=1)
    until = yesterday(tzinfo=tzinfo, now=now)
    if first > until or level not in _ID_COLUMNS:
        return Aftermath()
    figures = _sums(
        db, owner=owner, level=level, external_id=external_id, since=first, until=until
    )
    leads, qualified = _lead_counts(level)(
        db, owner=owner, since=start_of(first, tzinfo), until=end_of(until, tzinfo)
    ).get(external_id, (0, 0))
    return Aftermath(
        totals=Totals(
            spend_minor=figures["spend_minor"],
            impressions=figures["impressions"],
            clicks=figures["clicks"],
            leads=leads,
            qualified=qualified,
            leads_reported=figures["leads_reported"],
            results=figures["results"],
            recallers=figures["recallers"],
            profile_visits=figures["profile_visits"],
        ),
        link_clicks=figures["link_clicks"],
        days=figures["days"],
    )


def _sums(
    db: Session, *, owner: User, level: str, external_id: str, since: date, until: date
) -> dict[str, int]:
    m = MetricsDaily
    picked: dict[str, Any] = {
        "spend_minor": func.sum(m.spend_minor),
        "impressions": func.sum(m.impressions),
        "clicks": func.sum(m.clicks),
        "link_clicks": func.sum(m.inline_link_clicks),
        "leads_reported": func.sum(m.leads_reported),
        "results": func.sum(m.results_reported),
        "recallers": func.sum(m.recallers),
        "profile_visits": func.sum(m.profile_visits),
        "days": func.count(distinct(m.date)),
    }
    row = (
        db.execute(
            select(*(column.label(name) for name, column in picked.items())).where(
                *cabinet_where(db, owner=owner, level=level, account=EVERY_ACCOUNT),
                m.date >= since,
                m.date <= until,
                getattr(m, _ID_COLUMNS[level]) == external_id,
            )
        )
        .mappings()
        .one()
    )
    return {key: int(row[key] or 0) for key in picked}


__all__ = ["after_figures"]
