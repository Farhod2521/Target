from datetime import date, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.creatives import creative_ids_by_ad
from app.modules.metrics.constants import EVERY_ACCOUNT, MetricLevel, Ranking
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.facts import cabinet_where

RANKING_DAYS: Final = 7
Verdicts = tuple[str, str, str]


def rankings(
    db: Session, *, owner: User, campaign: Any, until: date
) -> dict[str, Verdicts]:
    m = MetricsDaily
    rows = list(
        db.execute(
            select(
                m.external_id,
                m.quality_ranking,
                m.engagement_rate_ranking,
                m.conversion_rate_ranking,
            )
            .where(
                *cabinet_where(
                    db, owner=owner, level=MetricLevel.AD, account=EVERY_ACCOUNT
                ),
                m.provider == campaign.provider,
                m.campaign_external_id == campaign.external_id,
                m.date >= until - timedelta(days=RANKING_DAYS - 1),
                m.date <= until,
                m.quality_ranking != "",
            )
            .order_by(m.date.desc())
        )
    )
    creative_of = creative_ids_by_ad(
        db,
        owner=owner,
        provider=campaign.provider,
        ad_external_ids=sorted({row.external_id for row in rows}),
    )
    found: dict[str, Verdicts] = {}
    labels = dict(Ranking.choices)
    for row in rows:
        creative_id = creative_of.get(row.external_id, "")
        if not creative_id or creative_id in found:
            continue
        found[creative_id] = (
            _label(labels, row.quality_ranking),
            _label(labels, row.engagement_rate_ranking),
            _label(labels, row.conversion_rate_ranking),
        )
    return found


def _label(labels: dict[str, Any], value: str) -> str:
    return str(labels.get(value, value))


__all__ = ["RANKING_DAYS", "Verdicts", "rankings"]
