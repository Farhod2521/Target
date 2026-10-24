"""Writing figure rows: upserts keyed the way Django's bulk_create keyed them."""

import logging
from datetime import datetime, timedelta
from typing import Any

from adskit.dto import MetricsDTO, PeopleCountDTO, SegmentMetricsDTO
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import (
    INSIGHTS_LOCK_SECONDS,
    REFUSED_SAMPLE,
    WRITE_BATCH,
    MetricLevel,
)
from app.modules.metrics.models import MetricsBreakdown, MetricsDaily, PeopleCount
from app.modules.metrics.selectors.facts import group_leads
from core.metrics import join_segment

logger = logging.getLogger(__name__)
DAILY_KEY = ["owner_id", "provider", "level", "external_id", "date"]
COPIED = (
    "campaign_external_id",
    "adset_external_id",
    "ad_external_id",
    "spend_minor",
    "currency",
    "impressions",
    "reach",
    "clicks",
    "leads_reported",
    "results_reported",
    "recallers",
    "profile_visits",
    "attribution_setting",
    "frequency",
    "ctr",
    "cpm_minor",
    "cpc_minor",
    "object_name",
    "unique_clicks",
    "inline_link_clicks",
    "unique_inline_link_clicks",
    "outbound_clicks",
    "landing_page_views",
    "video_plays",
    "video_thruplays",
    "video_p25",
    "video_p50",
    "video_p75",
    "video_p100",
    "video_views_3s",
    "reactions",
    "comments",
    "shares",
    "saves",
    "cost_per_lead_minor",
    "lead_value_minor",
    "quality_ranking",
    "engagement_rate_ranking",
    "conversion_rate_ranking",
)
REFRESHED = ("ad_account_id", *COPIED, "synced_at")


def _daily_row(
    *, ad_account: AdAccount, row: MetricsDTO, now: datetime, level: str
) -> dict[str, Any]:
    return {
        "owner_id": ad_account.owner_id,
        "ad_account_id": ad_account.id,
        "provider": ad_account.provider,
        "level": str(level),
        "external_id": row.ref.id,
        "date": row.day,
        **{name: getattr(row, name) for name in COPIED},
        "synced_at": now,
        "created_at": now,
        "updated_at": now,
    }


def _upsert_daily(db: Session, rows: list[dict[str, Any]]) -> None:
    statement = insert(MetricsDaily).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=DAILY_KEY,
        set_={name: statement.excluded[name] for name in (*REFRESHED, "updated_at")},
    )
    db.execute(statement)


def store_metrics(
    db: Session,
    *,
    ad_account: AdAccount,
    rows: list[MetricsDTO],
    now: datetime,
    level: str,
) -> int:
    if not rows:
        return 0
    if level == MetricLevel.CAMPAIGN:
        found = group_leads(
            db,
            ad_account=ad_account,
            campaign_ids={row.ref.id for row in rows},
            days={row.day for row in rows},
            synced_since=now - timedelta(seconds=INSIGHTS_LOCK_SECONDS),
        )
        rows = [
            row.model_copy(update={"leads_reported": found[(row.ref.id, row.day)]})
            if (row.ref.id, row.day) in found
            else row
            for row in rows
        ]
    made = [
        _daily_row(ad_account=ad_account, row=row, now=now, level=level) for row in rows
    ]
    refused: list[str] = []
    written = 0
    for start in range(0, len(made), WRITE_BATCH):
        batch = made[start : start + WRITE_BATCH]
        try:
            with db.begin_nested():
                _upsert_daily(db, batch)
            written += len(batch)
        except DataError:
            for one in batch:
                try:
                    with db.begin_nested():
                        _upsert_daily(db, [one])
                    written += 1
                except DataError:
                    lengths = {
                        k: len(v) for k, v in one.items() if isinstance(v, str) and v
                    }
                    logger.warning(
                        "figure row %s refused by the database: %s",
                        one["external_id"],
                        lengths,
                    )
                    refused.append(one["external_id"])
    db.commit()
    if refused:
        logger.error(
            "figure rows refused by the database",
            extra={
                "account": ad_account.external_id,
                "level": level,
                "refused": len(refused),
                "rows": refused[:REFUSED_SAMPLE],
            },
        )
    return written


BREAKDOWN_KEY = [
    "owner_id",
    "provider",
    "level",
    "external_id",
    "date",
    "breakdown_kind",
    "breakdown_value",
]
BREAKDOWN_REFRESHED = (
    "ad_account_id",
    "campaign_external_id",
    "adset_external_id",
    "ad_external_id",
    "spend_minor",
    "currency",
    "impressions",
    "reach",
    "clicks",
    "leads_reported",
    "synced_at",
    "updated_at",
)


def store_breakdowns(
    db: Session,
    *,
    ad_account: AdAccount,
    rows: list[SegmentMetricsDTO],
    now: datetime,
    level: str,
) -> int:
    if not rows:
        return 0
    made = [
        {
            "owner_id": ad_account.owner_id,
            "ad_account_id": ad_account.id,
            "provider": ad_account.provider,
            "level": str(level),
            "external_id": row.ref.id,
            "campaign_external_id": row.campaign_external_id,
            "adset_external_id": row.adset_external_id,
            "ad_external_id": row.ad_external_id,
            "date": row.day,
            "breakdown_kind": str(row.kind),
            "breakdown_value": join_segment(*row.segment_parts),
            "spend_minor": row.spend_minor,
            "currency": row.currency,
            "impressions": row.impressions,
            "reach": row.reach,
            "clicks": row.clicks,
            "leads_reported": row.leads_reported,
            "synced_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for row in rows
    ]
    for start in range(0, len(made), WRITE_BATCH):
        statement = insert(MetricsBreakdown).values(made[start : start + WRITE_BATCH])
        db.execute(
            statement.on_conflict_do_update(
                index_elements=BREAKDOWN_KEY,
                set_={name: statement.excluded[name] for name in BREAKDOWN_REFRESHED},
            )
        )
    db.commit()
    return len(made)


def replace_people(
    db: Session,
    *,
    ad_account: AdAccount,
    level: str,
    rows: list[PeopleCountDTO],
    now: datetime,
) -> int:
    db.execute(
        delete(PeopleCount).where(
            PeopleCount.ad_account_id == ad_account.id, PeopleCount.level == str(level)
        )
    )
    made = [
        {
            "owner_id": ad_account.owner_id,
            "ad_account_id": ad_account.id,
            "provider": ad_account.provider,
            "external_id": row.ref.id,
            "level": str(level),
            "campaign_external_id": row.campaign_external_id,
            "adset_external_id": row.adset_external_id,
            "ad_external_id": row.ad_external_id,
            "since": row.since,
            "until": row.until,
            "reach": row.reach,
            "recallers": row.recallers,
            "synced_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for row in rows
        if row.ref.id
    ]
    for start in range(0, len(made), WRITE_BATCH):
        db.execute(
            insert(PeopleCount)
            .values(made[start : start + WRITE_BATCH])
            .on_conflict_do_nothing()
        )
    db.commit()
    return len(made)
