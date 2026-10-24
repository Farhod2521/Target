"""What a campaign is for the figures: its name, delivery, the result it counts,
its kind; the spend built outside the product; and one ad's engagement."""

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from sqlalchemy import case, func, literal, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.metrics.constants import EVERY_ACCOUNT, MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors import periods
from app.modules.metrics.selectors.facts import cabinet_where
from app.modules.metrics.selectors.results import (
    counted_result,
    screen_kind,
    uncounted_note,
)
from core.ads.delivery import shown_delivery
from core.metrics import LEAD_GOALS, EngagementFigures, Outcome, campaign_goal
from core.metrics.outcomes import SITE_GOAL, SITE_LEAD_EVENT, outcome_for

DELIVERY_LABELS: dict[str, Any] = {
    "active": "Ishlayapti",
    "paused": "To'xtatilgan",
    "pending": "Tekshiruvda",
    "rejected": "Rad etilgan",
    "finished": "Tugagan",
    "unknown": "Noma'lum",
}


def goal_order() -> tuple[Any, ...]:
    """Which ad set speaks for its campaign: a form goal first, then a site lead."""
    from app.modules.ads.models import AdSet

    custom = type_coerce(AdSet.promoted_object_raw, JSONB)["custom_event_type"].astext
    return (
        case(
            (AdSet.optimization_goal_raw.in_(sorted(LEAD_GOALS)), literal(0)),
            (
                (AdSet.optimization_goal_raw == SITE_GOAL)
                & (custom == SITE_LEAD_EVENT),
                literal(1),
            ),
            else_=literal(2),
        ),
        AdSet.external_id,
    )


def adsets_kind(adsets: Iterable[Any]) -> Outcome:
    goal, promoted = campaign_goal(
        (
            row.external_id,
            row.optimization_goal_raw or "",
            _promoted(row.promoted_object_raw),
        )
        for row in adsets
    )
    return screen_kind(goal, promoted)


def campaign_goal_of(
    db: Session, *, owner: User, campaign: Any
) -> tuple[str, Mapping[str, Any] | None]:
    from app.modules.ads.models import AdSet

    rows = db.execute(
        select(
            AdSet.external_id, AdSet.optimization_goal_raw, AdSet.promoted_object_raw
        ).where(AdSet.owner_id == owner.id, AdSet.campaign_id == campaign.id)
    )
    return campaign_goal(
        (external_id, goal or "", promoted) for external_id, goal, promoted in rows
    )


def campaign_kind(db: Session, *, owner: User, campaign: Any) -> Outcome:
    return screen_kind(*campaign_goal_of(db, owner=owner, campaign=campaign))


def _promoted(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def campaign_meta(
    db: Session,
    *,
    owner: User,
    account: AdAccount | None = None,
    campaign_ids: frozenset[str] | None = None,
) -> dict[str, "periods.CampaignMeta"]:
    from app.modules.ads.models import Ad, AdSet, Campaign

    def speaker(column: Any) -> Any:
        return (
            select(column)
            .where(AdSet.owner_id == owner.id, AdSet.campaign_id == Campaign.id)
            .order_by(*goal_order())
            .limit(1)
            .correlate(Campaign)
            .scalar_subquery()
        )

    ad_states = (
        select(func.array_agg(aggregate_order_by(Ad.delivery.distinct(), Ad.delivery)))
        .join(AdSet, AdSet.id == Ad.adset_id)
        .where(Ad.owner_id == owner.id, AdSet.campaign_id == Campaign.id)
        .correlate(Campaign)
        .scalar_subquery()
    )
    query = select(
        Campaign.external_id,
        Campaign.name,
        Campaign.delivery,
        speaker(AdSet.optimization_goal_raw).label("goal_raw"),
        speaker(AdSet.promoted_object_raw).label("promoted_raw"),
        ad_states.label("ad_states"),
    ).where(Campaign.owner_id == owner.id)
    if campaign_ids is not None:
        query = query.where(Campaign.external_id.in_(list(campaign_ids)))
    elif account is not None:
        query = query.where(Campaign.ad_account_id == account.id)
    found: dict[str, periods.CampaignMeta] = {}
    for row in db.execute(query):
        delivery = shown_delivery(own=row.delivery, ads=row.ad_states or ())
        found[row.external_id] = meta_of(
            {
                "external_id": row.external_id,
                "name": row.name,
                "delivery": delivery,
                "goal_raw": row.goal_raw,
                "promoted_raw": row.promoted_raw,
            }
        )
    return found


def meta_of(row: dict[str, Any]) -> "periods.CampaignMeta":
    goal = row["goal_raw"] or ""
    promoted = _promoted(row["promoted_raw"])
    delivery = row["delivery"] or "unknown"
    return periods.CampaignMeta(
        name=row["name"] or row["external_id"],
        delivery=delivery,
        delivery_label=DELIVERY_LABELS.get(delivery, DELIVERY_LABELS["unknown"]),
        note=uncounted_note(goal, promoted),
        result=counted_result(goal, promoted),
        kind=outcome_for(goal, promoted),
        goal=goal,
    )


def elsewhere_spend(
    db: Session,
    *,
    owner: User,
    page: PageAccount,
    since: date,
    until: date,
    currency: str,
    account: AdAccount | None = None,
) -> int:
    """Money this page's adverts spent in campaigns built outside the product."""
    from app.modules.ads.selectors import all_launched_campaign_ids, page_scope

    spend = func.sum(MetricsDaily.spend_minor)
    rows = db.execute(
        select(MetricsDaily.adset_external_id, spend)
        .where(
            *cabinet_where(db, owner=owner, account=EVERY_ACCOUNT),
            MetricsDaily.date >= since,
            MetricsDaily.date <= until,
            MetricsDaily.currency == currency,
            MetricsDaily.campaign_external_id != "",
            MetricsDaily.adset_external_id != "",
            MetricsDaily.campaign_external_id.not_in(
                list(all_launched_campaign_ids(db, owner=owner))
            ),
        )
        .group_by(MetricsDaily.adset_external_id)
        .having(spend > 0)
    )
    spent = {str(adset): int(amount) for adset, amount in rows}
    if not spent:
        return 0
    whole = page_scope(db, owner=owner)
    scope = whole.only(
        page.external_id, account.external_id if account is not None else ""
    )
    known = set(whole.page_of) | whole.outside
    sole = len(whole.pages) == 1 and page.external_id in whole.pages
    return sum(
        amount
        for adset_id, amount in spent.items()
        if scope.page_of.get(adset_id) == page.external_id
        or (sole and adset_id not in known)
    )


def figures_of(row: MetricsDaily) -> EngagementFigures:
    return EngagementFigures(
        impressions=row.impressions,
        reach=row.reach,
        clicks=row.clicks,
        unique_clicks=row.unique_clicks,
        inline_link_clicks=row.inline_link_clicks,
        outbound_clicks=row.outbound_clicks,
        video_plays=row.video_plays,
        video_views_3s=row.video_views_3s,
        video_thruplays=row.video_thruplays,
        video_p100=row.video_p100,
        spend_minor=row.spend_minor,
        lead_value_minor=row.lead_value_minor,
    )


def engagement_on(
    db: Session,
    *,
    owner: User,
    external_id: str,
    day: date,
    level: str = MetricLevel.AD,
) -> EngagementFigures | None:
    row = db.scalars(
        select(MetricsDaily)
        .where(
            *cabinet_where(db, owner=owner, level=level),
            MetricsDaily.external_id == external_id,
            MetricsDaily.date == day,
        )
        .limit(1)
    ).first()
    return None if row is None else figures_of(row)
