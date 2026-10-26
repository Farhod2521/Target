"""The account's money as the provider reads it, and what a sync found stopped
among the advertising launched from here."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from adskit import registry
from adskit.dto import AccountStateDTO
from adskit.errors import PortNotAvailable, ProviderError
from adskit.refs import ExternalRef, ProviderName
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads.constants import NOT_RUNNING, Delivery, ManagedLevel, StopReason
from app.modules.ads.exceptions import ConnectionUnusable
from app.modules.ads.models import Ad, AdSet, Campaign, DeliveryStop
from app.modules.audit.constants import ActionStatus, EventName
from app.modules.audit.models import ActionLog
from app.modules.integrations.models import AdAccount

logger = logging.getLogger(__name__)
OURS_WINDOW = timedelta(hours=26)
ACCOUNT: Final = "account"
_BLOCKED = frozenset({"payment_failed", "disabled_payment", "disabled", "closed"})


@dataclass(frozen=True, slots=True)
class Row:
    """One object launched from here, as the mirror holds it."""

    level: str
    external_id: str
    name: str
    campaign_id: str
    parent_id: str
    delivery: str


# -- the account's money ---------------------------------------------------------------


def _account_ref(ad_account: AdAccount) -> ExternalRef:
    return ExternalRef(
        provider=ProviderName(ad_account.provider),
        level="account",
        id=ad_account.external_id,
    )


def read_account_state(ad_account: AdAccount) -> AccountStateDTO | None:
    """Whether the account can pay for its advertising, or nothing."""
    from app.modules.ads.services.access import token_for

    try:
        return registry.get(ad_account.provider).campaigns.read_account(
            account=_account_ref(ad_account), token=token_for(ad_account=ad_account)
        )
    except (PortNotAvailable, ProviderError, ConnectionUnusable) as exc:
        logger.info("account state of %s not read: %s", ad_account.external_id, exc)
        return None


def refresh_account_state(
    db: Session, *, ad_account: AdAccount, campaigns: Any, token: str
) -> None:
    """Read and store the account's money now, outside a sync."""
    try:
        state = campaigns.read_account(account=_account_ref(ad_account), token=token)
    except (PortNotAvailable, ProviderError) as exc:
        logger.info("account state of %s not read: %s", ad_account.external_id, exc)
        return
    store_account_state(db, ad_account=ad_account, state=state)


def store_account_state(
    db: Session, *, ad_account: AdAccount, state: AccountStateDTO
) -> None:
    """Write what the provider said, keeping what it did not answer."""
    known = state.standing != "unknown"
    ad_account.standing = state.standing
    ad_account.account_status = state.raw_status or ad_account.account_status
    ad_account.disable_reason = state.raw_reason
    ad_account.may_advertise = state.standing not in _BLOCKED if known else None
    ad_account.payment_due = state.standing == "payment_failed" if known else None
    ad_account.spend_cap_minor = state.spend_cap_minor
    ad_account.amount_spent_minor = state.amount_spent_minor
    ad_account.balance_minor = state.balance_minor
    if state.prepaid is not None:
        ad_account.prepaid = state.prepaid
    db.flush()


# -- the stops -------------------------------------------------------------------------


def our_rows(db: Session, *, ad_account: AdAccount) -> dict[tuple[str, str], Row]:
    """Every campaign, group and advert on this account that we launched."""
    from app.modules.ads.selectors.launched import all_launched_campaign_ids

    owner = ad_account.owner
    ours = all_launched_campaign_ids(db, owner=owner)
    if not ours:
        return {}
    found: dict[tuple[str, str], Row] = {}
    queries: tuple[tuple[str, Any], ...] = (
        (
            ManagedLevel.CAMPAIGN,
            select(
                Campaign.external_id,
                Campaign.name,
                Campaign.external_id,
                Campaign.external_id,
                Campaign.delivery,
            ).where(
                Campaign.owner_id == owner.id,
                Campaign.ad_account_id == ad_account.id,
                Campaign.external_id.in_(ours),
            ),
        ),
        (
            ManagedLevel.ADSET,
            select(
                AdSet.external_id,
                AdSet.name,
                Campaign.external_id,
                Campaign.external_id,
                AdSet.delivery,
            )
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                AdSet.owner_id == owner.id,
                Campaign.ad_account_id == ad_account.id,
                Campaign.external_id.in_(ours),
            ),
        ),
        (
            ManagedLevel.AD,
            select(
                Ad.external_id,
                Ad.name,
                Campaign.external_id,
                AdSet.external_id,
                Ad.delivery,
            )
            .join(AdSet, AdSet.id == Ad.adset_id)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(
                Ad.owner_id == owner.id,
                Campaign.ad_account_id == ad_account.id,
                Campaign.external_id.in_(ours),
            ),
        ),
    )
    for level, query in queries:
        for external_id, name, campaign_id, parent_id, delivery in db.execute(query):
            found[level, external_id] = Row(
                level=level,
                external_id=external_id,
                name=name,
                campaign_id=campaign_id,
                parent_id=parent_id,
                delivery=delivery,
            )
    return found


def note_stops(
    db: Session,
    *,
    ad_account: AdAccount,
    before: dict[tuple[str, str], Row],
    state: AccountStateDTO | None,
    now: datetime,
) -> list[DeliveryStop]:
    """Open a row for every new stop, close the ones that came back. Commits."""
    from app.modules.audit.services import emit

    after = our_rows(db, ad_account=ad_account)
    opened = _switched_off(
        db, ad_account=ad_account, before=before, after=after, now=now
    )
    opened += _money(db, ad_account=ad_account, after=after, state=state, now=now)
    for stop in opened:
        emit(
            db,
            owner_id=ad_account.owner_id,
            name=EventName.DELIVERY_STOPPED,
            aggregate_type="ad_object",
            aggregate_id=stop.external_id,
            payload={"level": stop.level, "reason": stop.reason},
            occurred_at=now,
        )
    db.commit()
    return opened


def _open_stops(db: Session, ad_account: AdAccount, *where: Any) -> list[DeliveryStop]:
    return list(
        db.scalars(
            select(DeliveryStop).where(
                DeliveryStop.owner_id == ad_account.owner_id,
                DeliveryStop.ad_account_id == ad_account.id,
                DeliveryStop.cleared_at.is_(None),
                *where,
            )
        )
    )


def _switched_off(
    db: Session,
    *,
    ad_account: AdAccount,
    before: dict[tuple[str, str], Row],
    after: dict[tuple[str, str], Row],
    now: datetime,
) -> list[DeliveryStop]:
    """Switches found off since the last sync that nobody here turned off."""
    off = {
        key: row
        for key, row in after.items()
        if row.delivery == Delivery.PAUSED
        and key in before
        and before[key].delivery not in NOT_RUNNING
    }
    off_ids = {external_id for _level, external_id in off}
    ours = (
        set(
            db.scalars(
                select(ActionLog.target_external_id).where(
                    ActionLog.owner_id == ad_account.owner_id,
                    ActionLog.target_external_id.in_(off_ids),
                    ActionLog.status.in_(
                        [str(ActionStatus.PENDING), str(ActionStatus.APPLIED)]
                    ),
                    ActionLog.created_at >= now - OURS_WINDOW,
                )
            )
        )
        if off_ids
        else set()
    )
    opened = [
        _open(
            db, ad_account=ad_account, row=row, reason=StopReason.ADS_MANAGER, now=now
        )
        for row in off.values()
        if row.external_id not in ours
        and row.parent_id not in off_ids - {row.external_id}
        and row.campaign_id not in off_ids - {row.external_id}
    ]
    for stop in _open_stops(
        db, ad_account, DeliveryStop.reason == str(StopReason.ADS_MANAGER)
    ):
        row = after.get((stop.level, stop.external_id))
        if row is None or row.delivery != Delivery.PAUSED:
            stop.cleared_at = now
    db.flush()
    return [stop for stop in opened if stop is not None]


def money_reason(
    *, state: AccountStateDTO | None, billing_held: bool
) -> StopReason | None:
    """Why the account's money is in the way, or nothing."""
    prepaid = bool(state is not None and state.prepaid)
    spent = StopReason.BALANCE_USED_UP if prepaid else StopReason.CARD_DECLINED
    if state is not None:
        if state.standing in ("payment_failed", "disabled_payment"):
            return spent
        if state.cap_reached:
            return StopReason.SPEND_CAP
    if billing_held:
        return spent
    if state is not None and state.standing == "payment_grace":
        return StopReason.PAYMENT_GRACE
    if state is not None and state.standing == "payment_pending":
        return StopReason.PAYMENT_PENDING
    return None


def _money(
    db: Session,
    *,
    ad_account: AdAccount,
    after: dict[tuple[str, str], Row],
    state: AccountStateDTO | None,
    now: datetime,
) -> list[DeliveryStop]:
    switched_on = [
        row
        for row in after.values()
        if row.level == ManagedLevel.CAMPAIGN and row.delivery not in NOT_RUNNING
    ]
    reason = (
        money_reason(
            state=state,
            billing_held=any(
                row.delivery == Delivery.BILLING for row in after.values()
            ),
        )
        if switched_on
        else None
    )
    for stop in _open_stops(db, ad_account, DeliveryStop.level == ACCOUNT):
        if stop.reason != reason:
            stop.cleared_at = now
    db.flush()
    if reason is None:
        return []
    row = Row(
        level=ACCOUNT,
        external_id=ad_account.external_id,
        name=ad_account.name,
        campaign_id="",
        parent_id="",
        delivery="",
    )
    opened = _open(db, ad_account=ad_account, row=row, reason=reason, now=now)
    return [opened] if opened is not None else []


def _open(
    db: Session, *, ad_account: AdAccount, row: Row, reason: StopReason, now: datetime
) -> DeliveryStop | None:
    """A new open row, or nothing when this stop is already open."""
    found = db.scalar(
        select(DeliveryStop.id).where(
            DeliveryStop.owner_id == ad_account.owner_id,
            DeliveryStop.level == row.level,
            DeliveryStop.external_id == row.external_id,
            DeliveryStop.reason == str(reason),
            DeliveryStop.cleared_at.is_(None),
        )
    )
    if found is not None:
        return None
    stop = DeliveryStop(
        owner_id=ad_account.owner_id,
        ad_account_id=ad_account.id,
        level=row.level,
        external_id=row.external_id,
        name=row.name,
        campaign_external_id=row.campaign_id,
        reason=str(reason),
        detected_at=now,
    )
    db.add(stop)
    db.flush()
    return stop
