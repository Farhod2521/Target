"""What the office may say a launched campaign is doing.

The mirror is a copy. It is only as true as its last sync, and a sync stops
for an owner whose plan lapsed, whose account was switched off here, or whose
connection broke - after which the copy says "running" for ever. The office
reads the copy through these rules, so it never claims more than it knows:

* running: the campaign is on, at least one of its adverts is on, and the
  copy is fresh;
* deleted: the account was read whole after the launch and the campaign was
  not there - Meta lists no tombstones, absence is the deletion;
* stale: the copy says on, but it is older than one sweep cycle allows.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.orm import Session

from app.modules.ads.constants import (
    DELIVERY_LABELS,
    NOT_RUNNING,
    SYNC_STALE_MINUTES,
    Delivery,
)
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch
from app.modules.integrations.models import AdAccount

STALE_AFTER: Final = timedelta(minutes=SYNC_STALE_MINUTES)
# A sync reads Meta first and stamps the account when it has stored the lot,
# so a campaign made during that read is missing from a sync stamped after it.
READ_MARGIN: Final = timedelta(minutes=15)

DELETED: Final = "deleted"
STALE: Final = "stale"
NO_ADS: Final = "no_ads"
NOT_READ: Final = "not_read"
STATE_LABELS: Final[dict[str, str]] = {
    **{str(key): str(label) for key, label in DELIVERY_LABELS.items()},
    DELETED: "O'chirilgan",
    STALE: "Holati eskirgan",
    NO_ADS: "Reklamasi qolmagan",
    NOT_READ: "Hali o'qilmagan",
}


@dataclass(frozen=True, slots=True)
class Mirrored:
    """One campaign as the copy holds it."""

    delivery: str
    synced_at: datetime | None
    ads: int
    live_ads: int


@dataclass(frozen=True, slots=True)
class CampaignState:
    key: str
    label: str
    is_running: bool
    is_stale: bool
    synced_at: datetime | None


def is_stale(synced_at: datetime | None, *, now: datetime) -> bool:
    return synced_at is None or now - synced_at > STALE_AFTER


def running_clause(*, now: datetime) -> ColumnElement[bool]:
    """``Campaign`` rows the office counts as running, as SQL."""
    live_ad = (
        exists()
        .where(
            AdSet.campaign_id == Campaign.id,
            Ad.adset_id == AdSet.id,
            Ad.delivery == str(Delivery.ACTIVE),
        )
        .correlate(Campaign)
    )
    return (
        (Campaign.delivery == str(Delivery.ACTIVE))
        & (Campaign.synced_at >= now - STALE_AFTER)
        & live_ad
    )


def mirrored(db: Session, *, owner_id: Any, ids: frozenset[str]) -> dict[str, Mirrored]:
    if not ids:
        return {}
    ads = (
        select(
            AdSet.campaign_id.label("campaign_id"),
            func.count(Ad.id).label("ads"),
            func.count(Ad.id)
            .filter(Ad.delivery == str(Delivery.ACTIVE))
            .label("live_ads"),
        )
        .join(Ad, Ad.adset_id == AdSet.id)
        .where(AdSet.owner_id == owner_id)
        .group_by(AdSet.campaign_id)
        .subquery()
    )
    rows = db.execute(
        select(
            Campaign.external_id,
            Campaign.delivery,
            Campaign.synced_at,
            func.coalesce(ads.c.ads, 0),
            func.coalesce(ads.c.live_ads, 0),
        )
        .outerjoin(ads, ads.c.campaign_id == Campaign.id)
        .where(Campaign.owner_id == owner_id, Campaign.external_id.in_(list(ids)))
    )
    return {
        external_id: Mirrored(delivery or "unknown", synced_at, int(n), int(live))
        for external_id, delivery, synced_at, n, live in rows
    }


def _gone(launch: CampaignLaunch, account: AdAccount | None) -> bool:
    """The account was read whole after this launch made its campaign."""
    if account is None or not account.is_active or account.synced_at is None:
        return False
    made = launch.finished_at or launch.delivery_started_at or launch.created_at
    return made is not None and account.synced_at > made + READ_MARGIN


def campaign_state(
    *,
    launch: CampaignLaunch,
    shown: str | None,
    copy: Mirrored | None,
    account: AdAccount | None,
    now: datetime,
) -> CampaignState:
    """``shown`` is the delivery as the customer's screen draws it."""
    if copy is None or shown is None:
        key = DELETED if _gone(launch, account) else NOT_READ
        return CampaignState(key, STATE_LABELS[key], False, False, None)
    stale = is_stale(copy.synced_at, now=now)
    key = shown
    if key not in NOT_RUNNING and stale:
        key = STALE
    elif key == Delivery.ACTIVE and copy.ads == 0:
        key = NO_ADS
    running = key == Delivery.ACTIVE and copy.live_ads > 0
    return CampaignState(
        key=str(key),
        label=STATE_LABELS.get(str(key), STATE_LABELS["unknown"]),
        is_running=running,
        is_stale=stale,
        synced_at=copy.synced_at,
    )


def accounts_to_refresh(accounts: list[AdAccount], *, now: datetime) -> list[AdAccount]:
    """Accounts a full sync may read whose copy is no longer fresh."""
    return [
        account
        for account in accounts
        if account.is_active and is_stale(account.synced_at, now=now)
    ]
