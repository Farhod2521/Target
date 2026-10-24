from dataclasses import dataclass
from datetime import date
from typing import Final

from adskit import MinorUnits
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.creatives import creative_ids_by_ad
from app.modules.metrics.constants import EVERY_ACCOUNT, MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.facts import cabinet_where
from app.modules.metrics.selectors.results import words_for
from core.metrics import (
    MIN_SEGMENT_LEADS,
    Outcome,
    SegmentComparison,
    SegmentFigures,
    compare_segments,
)

_SUMMED: Final[dict[str, str]] = {
    "spend_minor": "spend_minor",
    "impressions": "impressions",
    "clicks": "clicks",
    "link_clicks": "inline_link_clicks",
    "leads": "leads_reported",
    "results": "results_reported",
    "recallers": "recallers",
    "profile_visits": "profile_visits",
    "video_plays": "video_plays",
    "video_p25": "video_p25",
    "video_p50": "video_p50",
    "video_p75": "video_p75",
    "video_p100": "video_p100",
    "reactions": "reactions",
    "comments": "comments",
    "shares": "shares",
    "saves": "saves",
}


@dataclass(frozen=True, slots=True)
class CreativeSums:
    spend_minor: MinorUnits
    impressions: int
    clicks: int
    link_clicks: int
    leads: int
    results: int
    days: int
    recallers: int = 0
    profile_visits: int = 0
    video_plays: int = 0
    video_p25: int = 0
    video_p50: int = 0
    video_p75: int = 0
    video_p100: int = 0
    reactions: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0


def sums_by_creative(
    db: Session,
    *,
    owner: User,
    provider: str,
    since: date,
    until: date,
    campaign_external_id: str = "",
) -> dict[str, CreativeSums]:
    m = MetricsDaily
    where = [
        *cabinet_where(
            db,
            owner=owner,
            level=MetricLevel.AD,
            account=EVERY_ACCOUNT if campaign_external_id else None,
        ),
        m.provider == provider,
        m.date >= since,
        m.date <= until,
        m.external_id != "",
    ]
    if campaign_external_id:
        where.append(m.campaign_external_id == campaign_external_id)
    columns = [getattr(m, column) for column in _SUMMED.values()]
    daily = list(db.execute(select(m.external_id, m.date, *columns).where(*where)))
    creative_of = creative_ids_by_ad(
        db,
        owner=owner,
        provider=provider,
        ad_external_ids=sorted({row.external_id for row in daily}),
    )
    totals: dict[str, dict[str, int]] = {}
    spent_on: dict[str, set[date]] = {}
    for row in daily:
        creative_id = creative_of.get(row.external_id)
        if not creative_id:
            continue
        into = totals.setdefault(creative_id, dict.fromkeys(_SUMMED, 0))
        for name, column in _SUMMED.items():
            into[name] += row._mapping[column] or 0
        if row._mapping["spend_minor"]:
            spent_on.setdefault(creative_id, set()).add(row.date)
    return {
        creative_id: CreativeSums(
            **(sums | {"spend_minor": MinorUnits(sums["spend_minor"])}),
            days=len(spent_on.get(creative_id, ())),
        )
        for creative_id, sums in totals.items()
    }


def compare_creatives(
    sums: dict[str, CreativeSums],
    *,
    kind: Outcome = "lead",
    min_leads: int = MIN_SEGMENT_LEADS,
) -> SegmentComparison:
    return compare_segments(
        [
            SegmentFigures(
                segment=creative_id,
                spend_minor=row.spend_minor,
                impressions=row.impressions,
                clicks=row.clicks,
                leads_reported=countable(row, kind=kind),
            )
            for creative_id, row in sums.items()
        ],
        min_leads=min_leads,
        per=words_for(kind).per,
    )


def countable(row: CreativeSums, *, kind: Outcome) -> int:
    field = _CREATIVE_FIELD.get(words_for(kind).field, words_for(kind).field)
    return int(getattr(row, field, 0) or 0) if field else 0


_CREATIVE_FIELD: Final[dict[str, str]] = {"leads_reported": "leads"}


def creative_costs(
    db: Session,
    *,
    owner: User,
    provider: str,
    since: date,
    until: date,
    campaign_external_id: str = "",
    kind: Outcome = "lead",
    min_leads: int = MIN_SEGMENT_LEADS,
) -> SegmentComparison:
    return compare_creatives(
        sums_by_creative(
            db,
            owner=owner,
            provider=provider,
            since=since,
            until=until,
            campaign_external_id=campaign_external_id,
        ),
        kind=kind,
        min_leads=min_leads,
    )
