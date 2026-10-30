"""The mirror rows a manage action can point at, and the action log around them."""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import reduce
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, joinedload, selectinload

from app.common.db import utcnow
from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    ACTION_STALE_MINUTES,
    ACTIONS_PER_CAMPAIGN,
    AUTO_SYNC_COOLING_MINUTES,
    MANAGE_LOG_PREFIX,
    MANAGED_ACCOUNT_PATH,
    MAX_SITES_PER_OWNER,
    NOT_RUNNING,
    SYNC_STALE_MINUTES,
    Delivery,
    ManagedLevel,
)
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign, SiteCheck
from app.modules.ads.selectors.launched import MIRRORS
from app.modules.ads.selectors.pages import campaign_on_page, pages_by_adset
from app.modules.integrations.models import AdAccount

_LOADS: dict[str, Any] = {
    ManagedLevel.CAMPAIGN: lambda: joinedload(Campaign.ad_account),
    ManagedLevel.ADSET: lambda: joinedload(AdSet.campaign).joinedload(
        Campaign.ad_account
    ),
    ManagedLevel.AD: lambda: (
        joinedload(Ad.adset).joinedload(AdSet.campaign).joinedload(Campaign.ad_account)
    ),
}


def managed_target(
    db: Session, *, owner: User, level: str, external_id: str
) -> Any | None:
    model = MIRRORS.get(level)
    if model is None:
        return None
    return db.scalars(
        select(model)
        .options(_LOADS[level]())
        .where(model.owner_id == owner.id, model.external_id == external_id)
        .limit(1)
    ).first()


def shown_target(
    db: Session, *, owner: User, level: str, external_id: str
) -> Any | None:
    from app.modules.integrations.selectors import enabled_pages, page_shown

    row = managed_target(db, owner=owner, level=level, external_id=external_id)
    if row is None:
        return None
    if isinstance(row, Campaign):
        return row if campaign_on_page(db, owner=owner, campaign=row) else None
    page = page_shown(enabled_pages(db, owner=owner))
    if page is None:
        return None
    group = row.adset.external_id if isinstance(row, Ad) else row.external_id
    found = pages_by_adset(db, owner=owner, adset_ids=[group]).get(group, "")
    return None if found and found != page.external_id else row


def _log() -> Any:
    from app.modules.audit.models import ActionLog

    return ActionLog


def in_flight(
    db: Session,
    *,
    owner: User,
    level: str,
    external_id: str,
    actions: Collection[str] = (),
) -> bool:
    from app.modules.audit.constants import ActionStatus

    log = _log()
    cutoff = utcnow() - timedelta(minutes=ACTION_STALE_MINUTES)
    query = select(log.id).where(
        log.owner_id == owner.id,
        log.target_level == level,
        log.target_external_id == external_id,
        log.status == str(ActionStatus.PENDING),
        log.created_at >= cutoff,
    )
    if actions:
        query = query.where(log.action.in_([str(a) for a in actions]))
    return db.scalar(query.limit(1)) is not None


@dataclass(frozen=True, slots=True)
class HistoryRow:
    log: Any
    level_label: str
    amount: str
    moment: str = ""


def campaign_history(
    db: Session, *, owner: User, campaign: Campaign
) -> list[HistoryRow]:
    log = _log()
    adsets = list(
        db.scalars(
            select(AdSet.external_id).where(
                AdSet.owner_id == owner.id, AdSet.campaign_id == campaign.id
            )
        )
    )
    ads = (
        list(
            db.scalars(
                select(Ad.external_id)
                .join(AdSet, AdSet.id == Ad.adset_id)
                .where(Ad.owner_id == owner.id, AdSet.external_id.in_(adsets))
            )
        )
        if adsets
        else []
    )
    ids = [campaign.external_id, *adsets, *ads]
    rows = db.scalars(
        select(log)
        .options(joinedload(log.actor))
        .where(
            log.owner_id == owner.id,
            log.target_external_id.in_(ids),
            log.idempotency_key.startswith(f"{MANAGE_LOG_PREFIX}:"),
        )
        .order_by(log.created_at.desc())
        .limit(ACTIONS_PER_CAMPAIGN)
    )
    labels = dict(ManagedLevel.choices)
    return [
        HistoryRow(
            log=row,
            level_label=str(labels.get(row.target_level, "")),
            amount=_amount(row),
            moment=_moment(row),
        )
        for row in rows
    ]


def _amount(row: Any) -> str:
    figure = row.request_payload.get("daily_budget_minor")
    if figure is None:
        figure = row.request_payload.get("spend_cap_minor")
    return format_minor(
        amount_minor=figure, currency=str(row.request_payload.get("currency", ""))
    )


def _moment(row: Any) -> str:
    stamp = str(row.request_payload.get("end_time", ""))
    return stamp[:10] if len(stamp) >= 10 else ""


def account_of(*, target: Any, level: str) -> AdAccount:
    return reduce(getattr, MANAGED_ACCOUNT_PATH[level].split("__"), target)


def budget_floor(*, target: Any, level: str) -> int:
    from core.targeting import daily_floor

    return daily_floor(
        account_minor=account_of(target=target, level=level).min_daily_budget_minor,
        optimization_goal=str(getattr(target, "optimization_goal_raw", "")),
    )


def latest_actions(
    db: Session, *, owner: User, external_ids: list[str]
) -> dict[str, Any]:
    if not external_ids:
        return {}
    log = _log()
    rows = db.scalars(
        select(log)
        .where(log.owner_id == owner.id, log.target_external_id.in_(external_ids))
        .order_by(log.target_external_id, log.created_at.desc())
        .ext(distinct_on(log.target_external_id))
    )
    return {row.target_external_id: row for row in rows}


def still_running(rows: Sequence[Any | None]) -> bool:
    from app.modules.audit.constants import ActionStatus

    cutoff = utcnow() - timedelta(minutes=ACTION_STALE_MINUTES)
    return any(
        row is not None
        and row.status == ActionStatus.PENDING
        and row.created_at >= cutoff
        for row in rows
    )


# -- the campaigns list ---------------------------------------------------------------


def cabinet_account(db: Session, *, owner: User) -> AdAccount | None:
    from app.modules.integrations.selectors import active_ad_account

    return active_ad_account(db, owner=owner)


def _listed(query: Any) -> Any:
    return query.options(
        joinedload(Campaign.ad_account), selectinload(Campaign.adsets)
    ).order_by(Campaign.created_time.desc().nulls_last(), Campaign.name)


def _counted(rows: list[Campaign]) -> list[Campaign]:
    for row in rows:
        row.adset_count = len(row.adsets)  # type: ignore[attr-defined]
    return rows


def campaigns_for(
    db: Session,
    *,
    owner: User,
    ad_account: AdAccount | None = None,
    external_ids: frozenset[str] | None = None,
) -> list[Campaign]:
    query = select(Campaign).where(Campaign.owner_id == owner.id)
    if external_ids is not None:
        query = query.where(Campaign.external_id.in_(list(external_ids)))
    else:
        account = (
            ad_account if ad_account is not None else cabinet_account(db, owner=owner)
        )
        if account is None:
            return []
        query = query.where(Campaign.ad_account_id == account.id)
    return _counted(list(db.scalars(_listed(query)).unique()))


def listed_campaign(
    db: Session, *, owner: User, campaign_id: uuid.UUID
) -> Campaign | None:
    found = _counted(
        list(
            db.scalars(
                _listed(
                    select(Campaign).where(
                        Campaign.owner_id == owner.id, Campaign.id == campaign_id
                    )
                )
            ).unique()
        )
    )
    campaign = found[0] if found else None
    if campaign is None or not campaign_on_page(db, owner=owner, campaign=campaign):
        return None
    return campaign


def campaign_detail(
    db: Session, *, owner: User, campaign_id: uuid.UUID
) -> Campaign | None:
    campaign = db.scalars(
        select(Campaign)
        .options(
            joinedload(Campaign.ad_account),
            selectinload(Campaign.adsets).selectinload(AdSet.ads),
        )
        .where(Campaign.owner_id == owner.id, Campaign.id == campaign_id)
    ).first()
    if campaign is None or not campaign_on_page(db, owner=owner, campaign=campaign):
        return None
    return campaign


def last_synced_at(
    db: Session, *, owner: User, accounts: Sequence[AdAccount] | None = None
) -> datetime | None:
    if accounts is None:
        account = cabinet_account(db, owner=owner)
        return account.synced_at if account is not None else None
    stamps = [account.synced_at for account in accounts]
    if not stamps or None in stamps:
        return None
    return min(stamp for stamp in stamps if stamp is not None)


def has_cooled(*, synced_at: datetime | None) -> bool:
    if synced_at is None:
        return True
    return utcnow() - synced_at >= timedelta(minutes=AUTO_SYNC_COOLING_MINUTES)


def is_stale(*, synced_at: datetime | None) -> bool:
    if synced_at is None:
        return False
    return utcnow() - synced_at > timedelta(minutes=SYNC_STALE_MINUTES)


def is_running(row: Campaign) -> bool:
    from app.modules.audit.constants import ActionType

    if str(row.delivery) not in NOT_RUNNING:
        return True
    last = getattr(row, "last_action", None)
    return (
        last is not None and last.action == ActionType.RESUME and still_running([last])
    )


def split_running(
    *, campaigns: list[Campaign]
) -> tuple[list[Campaign], list[Campaign]]:
    running = [row for row in campaigns if is_running(row)]
    return running, [row for row in campaigns if not is_running(row)]


# -- landing pages to check -----------------------------------------------------------


def _live_creatives() -> Any:
    return select(Ad.creative_external_id).where(
        Ad.delivery == str(Delivery.ACTIVE), Ad.creative_external_id != ""
    )


def live_landing_urls(db: Session, *, owner: User) -> list[str]:
    count = func.count(AdCreative.id)
    rows = db.execute(
        select(AdCreative.link_url, count)
        .where(
            AdCreative.owner_id == owner.id,
            AdCreative.external_id.in_(
                _live_creatives().where(Ad.owner_id == owner.id)
            ),
            AdCreative.link_url != "",
        )
        .group_by(AdCreative.link_url)
        .order_by(count.desc(), AdCreative.link_url)
        .limit(MAX_SITES_PER_OWNER)
    )
    return [str(url) for url, _n in rows]


def owners_to_check(db: Session) -> list[str]:
    linked = db.scalars(
        select(AdCreative.owner_id)
        .where(AdCreative.external_id.in_(_live_creatives()), AdCreative.link_url != "")
        .distinct()
    )
    checked = db.scalars(select(SiteCheck.owner_id).distinct())
    return sorted({str(owner_id) for owner_id in [*linked, *checked]})


def site_checks(db: Session, *, owner: User) -> list[SiteCheck]:
    return list(db.scalars(select(SiteCheck).where(SiteCheck.owner_id == owner.id)))
