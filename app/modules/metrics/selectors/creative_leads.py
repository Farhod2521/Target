from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.creatives import creative_ids_by_ad
from app.modules.leads.selectors import tallies_by_ad
from app.modules.metrics.constants import EVERY_ACCOUNT, MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.facts import cabinet_where


@dataclass(frozen=True, slots=True)
class CreativeLeads:
    leads: int = 0
    qualified: int = 0
    unmarked: int = 0

    @property
    def is_judged(self) -> bool:
        return self.leads > self.unmarked


def leads_by_creative(
    db: Session, *, owner: User, campaign: Any, since: date, until: date
) -> dict[str, CreativeLeads]:
    m = MetricsDaily
    mine = set(
        db.scalars(
            select(m.external_id)
            .where(
                *cabinet_where(
                    db, owner=owner, level=MetricLevel.AD, account=EVERY_ACCOUNT
                ),
                m.provider == campaign.provider,
                m.campaign_external_id == campaign.external_id,
                m.date >= since,
                m.date <= until,
                m.external_id != "",
            )
            .distinct()
        )
    )
    if not mine:
        return {}
    tzinfo = campaign.ad_account.tzinfo()
    tallies = [
        tally
        for tally in tallies_by_ad(
            db,
            owner=owner,
            since=datetime.combine(since, time.min).replace(tzinfo=tzinfo),
            until=datetime.combine(until + timedelta(days=1), time.min).replace(
                tzinfo=tzinfo
            ),
        )
        if tally.external_id in mine
    ]
    if not tallies:
        return {}
    creative_of = creative_ids_by_ad(
        db,
        owner=owner,
        provider=campaign.provider,
        ad_external_ids=sorted(tally.external_id for tally in tallies),
    )
    found: dict[str, CreativeLeads] = {}
    for tally in tallies:
        creative_id = creative_of.get(tally.external_id, "")
        if not creative_id:
            continue
        running = found.get(creative_id, CreativeLeads())
        found[creative_id] = CreativeLeads(
            leads=running.leads + tally.leads,
            qualified=running.qualified + tally.qualified,
            unmarked=running.unmarked + tally.unmarked,
        )
    return found


__all__ = ["CreativeLeads", "leads_by_creative"]
