from collections import defaultdict
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad, AdSet, Campaign
from core.ads.delivery import shown_delivery


def with_badges[Row: Campaign | AdSet](
    db: Session, *, owner: User, rows: list[Row]
) -> list[Row]:
    campaign_ids = {
        str(row.campaign.external_id if isinstance(row, AdSet) else row.external_id)
        for row in rows
    }
    by_campaign: defaultdict[str, set[str]] = defaultdict(set)
    by_adset: defaultdict[str, set[str]] = defaultdict(set)
    if campaign_ids:
        ads = db.execute(
            select(Campaign.external_id, AdSet.external_id, Ad.delivery)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(Ad.owner_id == owner.id, Campaign.external_id.in_(campaign_ids))
        )
        for campaign_id, adset_id, delivery in ads:
            by_campaign[campaign_id].add(delivery)
            by_adset[adset_id].add(delivery)
    for row in rows:
        states = by_adset if isinstance(row, AdSet) else by_campaign
        _show(row, shown_delivery(own=row.delivery, ads=states[row.external_id]))
    return rows


def with_tree_badge(*, campaign: Campaign) -> Campaign:
    states = {ad.delivery for adset in campaign.adsets for ad in adset.ads}
    _show(campaign, shown_delivery(own=campaign.delivery, ads=states))
    return campaign


def _show(row: Campaign | AdSet, shown: str) -> None:
    row.badge = Delivery(shown)  # type: ignore[union-attr]
    controls = getattr(row, "controls", None)
    # On itself, off below: drawn as stopped, so the press it offers is a start.
    if (
        isinstance(row, Campaign)
        and controls is not None
        and shown == Delivery.PAUSED
        and row.delivery == Delivery.ACTIVE
    ):
        row.controls = replace(  # type: ignore[attr-defined]
            controls, can_resume=not controls.watched_account
        )


__all__ = ["with_badges", "with_tree_badge"]
