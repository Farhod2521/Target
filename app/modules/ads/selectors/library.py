"""Library files: which may be taken off the account, what shows them; ad forms; spread."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.money import format_minor, provider_money
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    LIBRARY_WORK_FRESH_MINUTES,
    Delivery,
    LaunchStatus,
    MediaKind,
)
from app.modules.ads.models import (
    Ad,
    AdCreative,
    AdSet,
    CampaignLaunch,
    LaunchCreative,
    MediaAsset,
)
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.leads.selectors.reads import FormOption
from core.targeting.budget import ads_budget_carries, daily_floor, per_ad_floor

LIBRARY_FILE_KINDS: Final = (MediaKind.IMAGE, MediaKind.VIDEO)
DELETE_REFUSED_SHOWN_MINUTES: Final = 60
_CREATIVE_GONE: Final = "DELETED"
_LAUNCHED: Final = (str(LaunchStatus.CREATING), str(LaunchStatus.CREATED))


def library_file(
    db: Session, *, owner: User, asset_id: UUID | str
) -> MediaAsset | None:
    """One file the owner may take off their ad account's library."""
    try:
        pk = UUID(str(asset_id))
    except ValueError:
        return None
    return db.scalar(
        select(MediaAsset).where(
            MediaAsset.owner_id == owner.id,
            MediaAsset.id == pk,
            MediaAsset.kind.in_([str(kind) for kind in LIBRARY_FILE_KINDS]),
            MediaAsset.ad_account_id.is_not(None),
        )
    )


def media_usage(
    db: Session, *, owner: User, assets: Iterable[MediaAsset]
) -> dict[UUID, int]:
    """How many adverts each library file is in, from what we already hold."""
    files = [a for a in assets if a.kind in LIBRARY_FILE_KINDS and a.ad_account_id]
    if not files:
        return {}
    accounts = {a.ad_account_id for a in files}
    hashes = {a.external_id for a in files if a.kind == MediaKind.IMAGE}
    videos = {a.external_id for a in files if a.kind == MediaKind.VIDEO}
    shown = (
        AdCreative.owner_id == owner.id,
        AdCreative.ad_account_id.in_(accounts),
        AdCreative.status != _CREATIVE_GONE,
    )
    mirrored: dict[tuple[str, object, str], int] = {}
    if hashes:
        for account_id, image_hash, n in db.execute(
            select(
                AdCreative.ad_account_id,
                AdCreative.image_hash,
                func.count(AdCreative.id),
            )
            .where(*shown, AdCreative.image_hash.in_(hashes))
            .group_by(AdCreative.ad_account_id, AdCreative.image_hash)
        ):
            mirrored[(str(MediaKind.IMAGE), account_id, image_hash)] = n
    if videos:
        for account_id, video_id, n in db.execute(
            select(
                AdCreative.ad_account_id, AdCreative.video_id, func.count(AdCreative.id)
            )
            .where(*shown, AdCreative.video_id.in_(videos))
            .group_by(AdCreative.ad_account_id, AdCreative.video_id)
        ):
            mirrored[(str(MediaKind.VIDEO), account_id, video_id)] = n
    launched = Counter(
        db.scalars(
            select(LaunchCreative.media_asset_id)
            .join(CampaignLaunch, CampaignLaunch.id == LaunchCreative.launch_id)
            .where(
                LaunchCreative.owner_id == owner.id,
                LaunchCreative.media_asset_id.in_([a.id for a in files]),
                CampaignLaunch.status.in_(_LAUNCHED),
            )
        )
    )
    return {
        a.id: max(
            mirrored.get((str(a.kind), a.ad_account_id, a.external_id), 0),
            launched.get(a.id, 0),
        )
        for a in files
    }


def _media_deletes(
    db: Session, *, owner: User, status: str, since: datetime
) -> frozenset[str]:
    query = select(ActionLog.target_external_id).where(
        ActionLog.owner_id == owner.id,
        ActionLog.action == str(ActionType.MEDIA_DELETE),
        ActionLog.status == status,
        ActionLog.created_at >= since,
    )
    if status == str(ActionStatus.FAILED):
        query = query.where(ActionLog.error_code != "gone")
    return frozenset(db.scalars(query))


def deleting_files(db: Session, *, owner: User, now: datetime) -> frozenset[str]:
    since = now - timedelta(minutes=LIBRARY_WORK_FRESH_MINUTES)
    return _media_deletes(
        db, owner=owner, status=str(ActionStatus.PENDING), since=since
    )


def failed_deletes(db: Session, *, owner: User, now: datetime) -> frozenset[str]:
    since = now - timedelta(minutes=DELETE_REFUSED_SHOWN_MINUTES)
    return _media_deletes(db, owner=owner, status=str(ActionStatus.FAILED), since=since)


def stills_pending(
    db: Session, *, owner: User, ad_account_id: UUID | None, now: datetime
) -> frozenset[UUID]:
    """New videos in this account's library still waiting for a frame."""
    if ad_account_id is None:
        return frozenset()
    since = now - timedelta(minutes=LIBRARY_WORK_FRESH_MINUTES)
    return frozenset(
        db.scalars(
            select(MediaAsset.id).where(
                MediaAsset.owner_id == owner.id,
                MediaAsset.ad_account_id == ad_account_id,
                MediaAsset.kind == str(MediaKind.VIDEO),
                MediaAsset.thumbnail_url == "",
                MediaAsset.created_at >= since,
            )
        )
    )


# -- the forms a running advert may open ----------------------------------------------


@dataclass(frozen=True, slots=True)
class AdForms:
    current_id: str
    current_name: str
    options: tuple[FormOption, ...] = ()


def ad_forms(db: Session, *, owner: User, ad: Ad) -> AdForms | None:
    """The choice for the edit dialog, or nothing where there is none to make."""
    from app.modules.ads.services.swap import form_page
    from app.modules.leads.selectors.reads import forms_by_external_id, usable_forms

    page = form_page(db, owner=owner, ad=ad)
    if page is None:
        return None
    current = forms_by_external_id(
        db, owner=owner, provider=ad.provider, external_ids=[ad.lead_form_external_id]
    )[ad.lead_form_external_id]
    choices = usable_forms(db, owner=owner, page=page, limit=None)
    return AdForms(
        current_id=ad.lead_form_external_id,
        current_name=current.name,
        options=tuple(
            option
            for option in choices.options
            if option.external_id != ad.lead_form_external_id
        ),
    )


def form_advert(db: Session, *, owner: User, adset_external_id: str) -> Ad | None:
    """The one delivering advert of a group that opens a form, or nothing."""
    found = list(
        db.scalars(
            select(Ad)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .where(
                Ad.owner_id == owner.id,
                AdSet.external_id == adset_external_id,
                Ad.delivery == str(Delivery.ACTIVE),
                Ad.lead_form_external_id != "",
            )
            .limit(2)
        )
    )
    return found[0] if len(found) == 1 else None


# -- how many pictures a budget carries -----------------------------------------------


@dataclass(frozen=True, slots=True)
class AdSpread:
    chosen: int
    carried: int
    per_ad_minor: int
    per_ad_label: str


def ad_spread(
    *,
    launch: CampaignLaunch,
    optimization_goal: str,
    ads: int,
    budget_minor: int | None = None,
) -> AdSpread | None:
    """The warning, or ``None`` when ``ads`` pictures fit the budget."""
    account = launch.ad_account
    money = (
        int(launch.daily_budget_minor or 0)
        if budget_minor is None
        else int(budget_minor)
    )
    if account is None or not money or ads < 2:
        return None
    floor = daily_floor(
        account_minor=int(account.min_daily_budget_minor or 0),
        optimization_goal=optimization_goal,
    )
    carried = ads_budget_carries(daily_budget_minor=money, floor_minor=floor, ads=ads)
    if carried >= ads:
        return None
    per_ad = per_ad_floor(floor_minor=floor)
    places = provider_money(provider=launch.provider).decimal_places(launch.currency)
    return AdSpread(
        chosen=ads,
        carried=carried,
        per_ad_minor=per_ad,
        per_ad_label=format_minor(
            amount_minor=per_ad, currency=launch.currency, places=places
        ),
    )
