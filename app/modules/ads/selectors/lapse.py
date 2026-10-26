"""A lapsed subscription's hold: what to switch off, and when to delete."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from metaads.writing import is_dry_run_id
from sqlalchemy import select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import (
    LAPSE_LAST_WARNING,
    LAPSE_MARK,
    NOT_RUNNING,
    LaunchStatus,
    LaunchStep,
    ManagedLevel,
)
from app.modules.ads.models import (
    AdSet,
    Campaign,
    CampaignLaunch,
    GoogleLaunch,
    LapseHold,
)
from app.modules.ads.selectors.launched import shared_campaign_ids


@dataclass(frozen=True, slots=True)
class LapseTarget:
    level: str
    external_id: str
    ad_account_id: uuid.UUID
    running: bool


def lapse_targets(db: Session, *, owner: User) -> list[LapseTarget]:
    campaigns, adsets = _made_ids(db, owner=owner)
    found = [
        LapseTarget(ManagedLevel.CAMPAIGN, external_id, account, _spends(delivery))
        for external_id, account, delivery in db.execute(
            select(
                Campaign.external_id, Campaign.ad_account_id, Campaign.delivery
            ).where(Campaign.owner_id == owner.id, Campaign.external_id.in_(campaigns))
        )
    ]
    found += [
        LapseTarget(ManagedLevel.ADSET, external_id, account, _spends(delivery))
        for external_id, account, delivery in db.execute(
            select(AdSet.external_id, Campaign.ad_account_id, AdSet.delivery)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(AdSet.owner_id == owner.id, AdSet.external_id.in_(adsets))
        )
    ]
    return found


def _made_ids(db: Session, *, owner: User) -> tuple[set[str], set[str]]:
    shared = shared_campaign_ids(db, owner=owner)
    campaigns: set[str] = set()
    adsets: set[str] = set()
    for refs in _created(db, CampaignLaunch, owner=owner):
        campaign = ref_field.first_id(refs, LaunchStep.CAMPAIGN)
        if campaign in shared:
            adsets.update(ref_field.ref_ids(refs, LaunchStep.ADSET))
        elif campaign:
            campaigns.add(campaign)
    for refs in _created(db, GoogleLaunch, owner=owner):
        campaigns.add(str(refs.get("campaign") or ""))
    return _real(campaigns), _real(adsets)


def _created(db: Session, model: Any, *, owner: User) -> Iterable[dict[str, Any]]:
    return [
        refs or {}
        for refs in db.scalars(
            select(model.created_refs).where(
                model.owner_id == owner.id, model.status == str(LaunchStatus.CREATED)
            )
        )
    ]


def _real(ids: set[str]) -> set[str]:
    return {
        external_id
        for external_id in ids
        if external_id and not is_dry_run_id(external_id)
    }


def _spends(delivery: str) -> bool:
    return str(delivery) not in NOT_RUNNING


def lapse_candidates(db: Session, *, now: datetime) -> dict[uuid.UUID, datetime]:
    from app.modules.billing.selectors import lapsed_deadlines

    makers = set(_makers(db, CampaignLaunch)) | set(_makers(db, GoogleLaunch))
    ended = lapsed_deadlines(db, owner_ids=makers, now=now)
    held: dict[uuid.UUID, datetime] = {}
    if ended:
        for owner_id, ended_at in db.execute(
            select(LapseHold.owner_id, LapseHold.ended_at)
            .where(LapseHold.owner_id.in_(list(ended)))
            .order_by(LapseHold.owner_id, LapseHold.ended_at.desc())
        ):
            held.setdefault(owner_id, ended_at)
    return {
        owner_id: deadline
        for owner_id, deadline in ended.items()
        if owner_id not in held or held[owner_id] < deadline
    }


def _makers(db: Session, model: Any) -> Iterable[uuid.UUID]:
    return db.scalars(
        select(model.owner_id)
        .where(model.status == str(LaunchStatus.CREATED))
        .distinct()
    )


def open_holds(db: Session) -> list[LapseHold]:
    return list(
        db.scalars(
            select(LapseHold)
            .where(LapseHold.resumed_at.is_(None), LapseHold.deleted_at.is_(None))
            .order_by(LapseHold.started_at)
        )
    )


def open_hold(db: Session, *, owner: User) -> LapseHold | None:
    return db.scalars(
        select(LapseHold)
        .where(
            LapseHold.owner_id == owner.id,
            LapseHold.resumed_at.is_(None),
            LapseHold.deleted_at.is_(None),
        )
        .order_by(LapseHold.started_at.desc())
        .limit(1)
    ).first()


def hold_stops(db: Session, *, hold: LapseHold) -> list[Any]:
    from app.modules.audit.constants import ActionType
    from app.modules.audit.models import ActionLog

    payload = type_coerce(ActionLog.request_payload, JSONB)
    return list(
        db.scalars(
            select(ActionLog)
            .where(
                ActionLog.owner_id == hold.owner_id,
                ActionLog.action == str(ActionType.PAUSE),
                payload[LAPSE_MARK].astext == str(hold.id),
            )
            .order_by(ActionLog.created_at)
        )
    )


def stops_in_flight(stops: list[Any]) -> bool:
    from app.modules.audit.constants import ActionStatus

    return any(stop.status == ActionStatus.PENDING for stop in stops)


def last_warning_due(*, hold: LapseHold, now: datetime) -> bool:
    return (
        hold.is_open and hold.started_at + LAPSE_LAST_WARNING <= now < hold.delete_after
    )


def unwritable_account_ids(db: Session, *, owner: User) -> frozenset[uuid.UUID]:
    """The accounts a stop sent now could only be refused on."""
    from sqlalchemy import or_

    from app.modules.ads.constants import BLOCKED_STANDINGS
    from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
    from app.modules.integrations.models import AdAccount, ProviderConnection

    return frozenset(
        db.scalars(
            select(AdAccount.id)
            .join(ProviderConnection, ProviderConnection.id == AdAccount.connection_id)
            .where(
                AdAccount.owner_id == owner.id,
                or_(
                    ProviderConnection.status.not_in(
                        [str(s) for s in USABLE_CONNECTION_STATUSES]
                    ),
                    AdAccount.may_advertise.is_(False),
                    AdAccount.standing.in_(list(BLOCKED_STANDINGS)),
                ),
            )
        )
    )
