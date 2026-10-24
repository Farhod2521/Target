"""The mirror: an ad account's campaigns, ad sets, ads and creatives, read and stored."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from adskit import registry
from adskit.dto import AdDTO, AdSetDTO, CampaignDTO, IssueDTO, RecommendationDTO
from adskit.errors import (
    AuthFailed,
    PermissionDenied,
    ProviderError,
    RateLimited,
    ResultTruncated,
)
from adskit.refs import ExternalRef, ProviderName
from sqlalchemy import delete, select
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.common import throttle
from app.common.cache import cache
from app.common.db import on_commit, utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    AUTO_SYNC_COOLING_MINUTES,
    MIRROR_SWEEP,
    PRESS_WINDOW_SECONDS,
    REFRESH_QUEUE,
    REFUSED_SAMPLE,
    SYNC_LOCK_SECONDS,
    SYNC_OUTCOME_KEY,
    SYNC_OUTCOME_SECONDS,
    SYNC_QUEUED,
    SYNC_RATE_LIMITED,
    SYNC_TRUNCATED,
)
from app.modules.ads.exceptions import (
    ConnectionUnusable,
    NoAdAccount,
    SyncAlreadyRunning,
    SyncFailed,
)
from app.modules.ads.models import Ad, AdCreative, AdSet, Campaign
from app.modules.ads.services.access import token_for
from app.modules.integrations.models import AdAccount

logger = logging.getLogger(__name__)
OPEN_BUCKET = "ads:sync-open"
OPEN_LIMIT = 1
PRESS_BUCKET = "ads:sync-press"


@dataclass(frozen=True, slots=True)
class SyncSummary:
    campaigns: int
    adsets: int
    ads: int
    creatives: int = 0
    refused: int = 0


# -- what an unread field keeps -------------------------------------------------------


def without(defaults: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in defaults.items() if key not in keys}


def only_filled(defaults: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in defaults.items() if value not in ("", {})}


def creatives_held(db: Session, *, owner: User, ads: Sequence[AdDTO]) -> set[str]:
    unread = {
        dto.creative.ref.id for dto in ads if dto.creative is not None and not dto.creative.story_raw
    }
    if not unread:
        return set()
    return set(
        db.scalars(
            select(AdCreative.external_id).where(
                AdCreative.owner_id == owner.id, AdCreative.external_id.in_(unread)
            )
        )
    )


def forms_still_known(db: Session, *, owner: User, ads: Sequence[AdDTO]) -> set[str]:
    unread = {
        dto.ref.id: dto.creative_external_id
        for dto in ads
        if not dto.lead_form_external_id and dto.creative_external_id
    }
    if not unread:
        return set()
    held = db.execute(
        select(Ad.external_id, Ad.creative_external_id).where(
            Ad.owner_id == owner.id,
            Ad.external_id.in_(list(unread)),
            Ad.lead_form_external_id != "",
        )
    )
    return {ad_id for ad_id, creative_id in held if unread[ad_id] == creative_id}


# -- writing rows ---------------------------------------------------------------------


def _issue_columns(issues: tuple[IssueDTO, ...]) -> dict[str, object]:
    return {
        "issues": [issue.model_dump() for issue in issues],
        "issue_codes": [issue.code for issue in issues if issue.code],
        "issue_summary": issues[0].summary if issues else "",
    }


def _advice(recommendations: tuple[RecommendationDTO, ...]) -> list[dict[str, object]]:
    return [item.model_dump(mode="json") for item in recommendations]


def _upsert(
    db: Session,
    model: Any,
    *,
    owner: User,
    provider: str,
    external_id: str,
    defaults: dict[str, Any],
    label: str,
    refused: list[str],
) -> Any | None:
    try:
        with db.begin_nested():
            row = db.scalars(
                select(model).where(model.provider == provider, model.external_id == external_id)
            ).first()
            if row is None:
                row = model(provider=provider, external_id=external_id)
                db.add(row)
            for key, value in defaults.items():
                setattr(row, key, value)
            db.flush()
    except DataError:
        lengths = {
            key: len(value) for key, value in defaults.items() if isinstance(value, str) and value
        }
        logger.warning("%s %s refused by the database: %s", label, external_id, lengths)
        refused.append(f"{label} {external_id}")
        return db.scalars(
            select(model).where(
                model.owner_id == owner.id,
                model.provider == provider,
                model.external_id == external_id,
            )
        ).first()
    return row


def _remove_missing(db: Session, model: Any, *where: Any, keep: set[str], label: str) -> None:
    removed = db.execute(
        delete(model)
        .where(*where, model.external_id.not_in(keep))
        .execution_options(synchronize_session=False)
    ).rowcount
    if removed:
        logger.info("sync removed %s stale %s rows", removed, label)


def write_campaigns(
    db: Session,
    *,
    ad_account: AdAccount,
    campaigns: Sequence[CampaignDTO],
    now: datetime,
    refused: list[str],
) -> dict[str, Campaign]:
    owner = ad_account.owner
    stored: dict[str, Campaign] = {}
    for dto in campaigns:
        campaign = _upsert(
            db,
            Campaign,
            owner=owner,
            provider=dto.ref.provider,
            external_id=dto.ref.id,
            label="campaign",
            refused=refused,
            defaults={
                "owner_id": owner.id,
                "ad_account_id": ad_account.id,
                "name": dto.name,
                "status": dto.status,
                "effective_status": dto.effective_status,
                "delivery": dto.delivery,
                "objective_raw": dto.objective_raw,
                "daily_budget_minor": dto.daily_budget_minor,
                "shared_budget_id": dto.shared_budget_id,
                "spend_cap_minor": dto.spend_cap_minor,
                "currency": dto.currency or ad_account.currency,
                "special_ad_categories": list(dto.special_ad_categories),
                "created_time": dto.created_time,
                **_issue_columns(dto.issues),
                "recommendations": _advice(dto.recommendations),
                "synced_at": now,
            },
        )
        if campaign is not None:
            stored[dto.ref.id] = campaign
    return stored


def write_adsets(
    db: Session,
    *,
    ad_account: AdAccount,
    adsets: Sequence[AdSetDTO],
    campaigns: dict[str, Campaign],
    now: datetime,
    refused: list[str],
) -> dict[str, AdSet]:
    owner = ad_account.owner
    stored: dict[str, AdSet] = {}
    for dto in adsets:
        campaign = campaigns.get(dto.campaign_ref.id)
        if campaign is None:
            logger.info("ad set %s skipped: campaign not in this sync", dto.ref.id)
            continue
        adset = _upsert(
            db,
            AdSet,
            owner=owner,
            provider=dto.ref.provider,
            external_id=dto.ref.id,
            label="ad set",
            refused=refused,
            defaults={
                "owner_id": owner.id,
                "campaign_id": campaign.id,
                "name": dto.name,
                "status": dto.status,
                "effective_status": dto.effective_status,
                "delivery": dto.delivery,
                "optimization_goal_raw": dto.optimization_goal_raw,
                "billing_event_raw": dto.billing_event_raw,
                "destination_type_raw": dto.destination_type_raw,
                "daily_budget_minor": dto.daily_budget_minor,
                "currency": dto.currency or ad_account.currency,
                "targeting_raw": dto.targeting_raw,
                "promoted_object_raw": dto.promoted_object_raw,
                "learning_status": dto.learning_status,
                "is_learning": dto.is_learning,
                "start_time": dto.start_time,
                "end_time": dto.end_time,
                **_issue_columns(dto.issues),
                "recommendations": _advice(dto.recommendations),
                "synced_at": now,
            },
        )
        if adset is not None:
            stored[dto.ref.id] = adset
    return stored


def write_ads(
    db: Session,
    *,
    ad_account: AdAccount,
    ads: Sequence[AdDTO],
    adsets: dict[str, AdSet],
    now: datetime,
    refused: list[str],
) -> set[str]:
    owner = ad_account.owner
    seen: set[str] = set()
    known_forms = forms_still_known(db, owner=owner, ads=ads)
    for dto in ads:
        adset = adsets.get(dto.adset_ref.id)
        if adset is None:
            logger.info("ad %s skipped: ad set not in this sync", dto.ref.id)
            continue
        defaults: dict[str, Any] = {
            "owner_id": owner.id,
            "adset_id": adset.id,
            "name": dto.name,
            "status": dto.status,
            "effective_status": dto.effective_status,
            "delivery": dto.delivery,
            "creative_external_id": dto.creative_external_id,
            "lead_form_external_id": dto.lead_form_external_id,
            **_issue_columns(dto.issues),
            "review_feedback": dto.review_feedback.model_dump() if dto.review_feedback else {},
            "synced_at": now,
        }
        if dto.ref.id in known_forms:
            defaults = without(defaults, "lead_form_external_id")
        ad = _upsert(
            db,
            Ad,
            owner=owner,
            provider=dto.ref.provider,
            external_id=dto.ref.id,
            label="ad",
            refused=refused,
            defaults=defaults,
        )
        if ad is not None:
            seen.add(dto.ref.id)
    return seen


def write_creatives(
    db: Session, *, ad_account: AdAccount, ads: Sequence[AdDTO], now: datetime, refused: list[str]
) -> set[str]:
    owner = ad_account.owner
    tried: set[str] = set()
    seen: set[str] = set()
    held = creatives_held(db, owner=owner, ads=ads)
    for dto in ads:
        creative = dto.creative
        if creative is None or creative.ref.id in tried:
            continue
        tried.add(creative.ref.id)
        defaults: dict[str, Any] = {
            "owner_id": owner.id,
            "ad_account_id": ad_account.id,
            "name": creative.name,
            "status": creative.status,
            "kind": creative.kind,
            "message": creative.message,
            "headline": creative.headline,
            "description": creative.description,
            "link_url": creative.link_url,
            "call_to_action": creative.call_to_action,
            "image_hash": creative.image_hash,
            "video_id": creative.video_id,
            "thumbnail_url": creative.thumbnail_url,
            "page_id": creative.page_id,
            "instagram_user_id": creative.instagram_user_id,
            "post_external_id": creative.post_external_id,
            "story_raw": creative.story_raw,
            "synced_at": now,
        }
        if creative.ref.id in held:
            defaults = only_filled(defaults)
        row = _upsert(
            db,
            AdCreative,
            owner=owner,
            provider=creative.ref.provider,
            external_id=creative.ref.id,
            label="creative",
            refused=refused,
            defaults=defaults,
        )
        if row is not None:
            seen.add(creative.ref.id)
    return seen


def store_everything(
    db: Session,
    *,
    ad_account: AdAccount,
    campaigns: list[CampaignDTO],
    adsets: list[AdSetDTO],
    ads: list[AdDTO],
) -> SyncSummary:
    now = utcnow()
    refused: list[str] = []
    owner_id = ad_account.owner_id
    stored_campaigns = write_campaigns(
        db, ad_account=ad_account, campaigns=campaigns, now=now, refused=refused
    )
    _remove_missing(
        db,
        Campaign,
        Campaign.owner_id == owner_id,
        Campaign.ad_account_id == ad_account.id,
        keep=set(stored_campaigns),
        label="campaign",
    )
    stored_adsets = write_adsets(
        db,
        ad_account=ad_account,
        adsets=adsets,
        campaigns=stored_campaigns,
        now=now,
        refused=refused,
    )
    on_account = select(Campaign.id).where(Campaign.ad_account_id == ad_account.id)
    _remove_missing(
        db,
        AdSet,
        AdSet.owner_id == owner_id,
        AdSet.campaign_id.in_(on_account),
        keep=set(stored_adsets),
        label="ad set",
    )
    stored_ads = write_ads(
        db, ad_account=ad_account, ads=ads, adsets=stored_adsets, now=now, refused=refused
    )
    groups = select(AdSet.id).where(AdSet.campaign_id.in_(on_account))
    _remove_missing(
        db, Ad, Ad.owner_id == owner_id, Ad.adset_id.in_(groups), keep=stored_ads, label="ad"
    )
    stored_creatives = write_creatives(
        db, ad_account=ad_account, ads=ads, now=now, refused=refused
    )
    _remove_missing(
        db,
        AdCreative,
        AdCreative.owner_id == owner_id,
        AdCreative.ad_account_id == ad_account.id,
        keep=stored_creatives,
        label="creative",
    )
    ad_account.synced_at = now
    db.commit()
    summary = SyncSummary(
        campaigns=len(stored_campaigns),
        adsets=len(stored_adsets),
        ads=len(stored_ads),
        creatives=len(stored_creatives),
        refused=len(refused),
    )
    if refused:
        logger.error(
            "mirror rows refused by the database",
            extra={
                "account": ad_account.external_id,
                "refused": len(refused),
                "rows": refused[:REFUSED_SAMPLE],
            },
        )
    logger.info("synced %s: %s", ad_account.external_id, summary)
    return summary


# -- reading from the provider --------------------------------------------------------


def list_everything(ad_account: AdAccount) -> tuple[list[CampaignDTO], list[AdSetDTO], list[AdDTO]]:
    token = token_for(ad_account=ad_account)
    bundle = registry.get(ad_account.provider)
    account = ExternalRef(
        provider=ProviderName(ad_account.provider), level="account", id=ad_account.external_id
    )
    return (
        bundle.campaigns.list_campaigns(account=account, token=token),
        bundle.campaigns.list_adsets(account=account, token=token),
        bundle.campaigns.list_ads(account=account, token=token),
    )


def read_everything(
    db: Session, ad_account: AdAccount
) -> tuple[list[CampaignDTO], list[AdSetDTO], list[AdDTO]]:
    try:
        return list_everything(ad_account)
    except PermissionDenied as exc:
        from app.modules.metrics.services import refusal_is_the_accounts

        if refusal_is_the_accounts(db, ad_account, exc=exc):
            logger.warning(
                "sync of %s refused with a working token: %s", ad_account.external_id, exc
            )
            raise SyncFailed from exc
        raise ConnectionUnusable from exc
    except AuthFailed as exc:
        from app.modules.integrations.constants import ConnectionStatus
        from app.modules.integrations.services import mark_unusable

        mark_unusable(
            db, connection=ad_account.connection, status=ConnectionStatus.INVALID, code=exc.code
        )
        db.commit()
        raise ConnectionUnusable from exc
    except ResultTruncated as exc:
        logger.error(
            "sync of %s truncated after %s pages (%s rows)",
            ad_account.external_id,
            exc.pages,
            exc.rows_read,
        )
        raise SyncFailed(cause=SYNC_TRUNCATED) from exc
    except RateLimited as exc:
        logger.warning("sync of %s rate limited: %s", ad_account.external_id, exc)
        raise SyncFailed(cause=SYNC_RATE_LIMITED) from exc
    except ProviderError as exc:
        logger.warning("sync of %s failed: %s", ad_account.external_id, exc)
        raise SyncFailed from exc


def mirror_lock_key(ad_account: AdAccount) -> str:
    return f"ads:sync:{ad_account.provider}:{ad_account.external_id}"


def sync_ad_account(db: Session, *, ad_account: AdAccount) -> SyncSummary:
    key = mirror_lock_key(ad_account)
    if not cache.add(key, "1", SYNC_LOCK_SECONDS):
        raise SyncAlreadyRunning
    try:
        campaigns, adsets, ads = read_everything(db, ad_account)
        return store_everything(
            db, ad_account=ad_account, campaigns=campaigns, adsets=adsets, ads=ads
        )
    finally:
        cache.delete(key)


# -- asking for a sync ----------------------------------------------------------------


def note_sync_outcome(*, sweep: str, ad_account_id: str, outcome: str) -> None:
    cache.set(
        SYNC_OUTCOME_KEY.format(sweep=sweep, account_id=ad_account_id),
        outcome,
        timeout=SYNC_OUTCOME_SECONDS,
    )


def request_sync(db: Session, *, user: User) -> tuple[AdAccount, ...]:
    from app.modules.ads.selectors import page_advertising

    accounts = page_advertising(db, owner=user).accounts
    if not accounts:
        raise NoAdAccount
    for account in accounts:
        if throttle.hit(
            bucket=PRESS_BUCKET,
            key=f"{account.provider}:{account.external_id}",
            limit=1,
            window_seconds=PRESS_WINDOW_SECONDS,
        ):
            _queue(db, account)
    return accounts


def sync_on_open(db: Session, *, user: User) -> bool:
    from app.modules.ads.selectors import has_cooled, page_advertising

    queued = False
    for account in page_advertising(db, owner=user).accounts:
        if not has_cooled(synced_at=account.synced_at):
            continue
        if throttle.hit(
            bucket=OPEN_BUCKET,
            key=f"{account.provider}:{account.external_id}",
            limit=OPEN_LIMIT,
            window_seconds=AUTO_SYNC_COOLING_MINUTES * 60,
        ):
            _queue(db, account)
            queued = True
    return queued


def _queue(db: Session, account: AdAccount) -> None:
    from app.modules.ads.tasks import sync_ad_account_task

    account_id = str(account.id)
    note_sync_outcome(sweep=MIRROR_SWEEP, ad_account_id=account_id, outcome=SYNC_QUEUED)
    on_commit(db, lambda: sync_ad_account_task.apply_async((account_id,), queue=REFRESH_QUEUE))


def resync_account(db: Session, *, ad_account: AdAccount, actor_id: str = "") -> None:
    from app.modules.ads.tasks import sync_ad_account_task, sync_media_task

    account_id = str(ad_account.id)
    logger.info("resync queued for account %s by %s", ad_account.external_id, actor_id or "-")
    on_commit(db, lambda: sync_ad_account_task.delay(account_id))
    on_commit(db, lambda: sync_media_task.delay(account_id))


# -- an account we only watch: keep the groups that run as our pages -------------------


def sync_watched_account(db: Session, *, ad_account: AdAccount) -> SyncSummary:
    from app.modules.integrations.selectors import enabled_pages
    from app.modules.metrics.services import watched_account_failures
    from core.ads import page_of_post, page_of_promoted

    key = mirror_lock_key(ad_account)
    if not cache.add(key, "1", SYNC_LOCK_SECONDS):
        raise SyncAlreadyRunning
    try:
        with watched_account_failures(db, ad_account, logger=logger):
            campaigns, adsets, ads = list_everything(ad_account)
        pages = {page.external_id for page in enabled_pages(db, owner=ad_account.owner)}
        by_advert: dict[str, str] = {}
        for row in sorted(ads, key=lambda item: item.ref.id):
            creative = row.creative
            if creative is None:
                continue
            page = creative.page_id or page_of_post(creative.post_external_id)
            if page:
                by_advert.setdefault(row.adset_ref.id, page)
        ours = [
            row
            for row in adsets
            if pages
            and (page_of_promoted(row.promoted_object_raw) or by_advert.get(row.ref.id, "")) in pages
        ]
        group_ids = {row.ref.id for row in ours}
        campaign_ids = {row.campaign_ref.id for row in ours}
        summary = store_everything(
            db,
            ad_account=ad_account,
            campaigns=[row for row in campaigns if row.ref.id in campaign_ids],
            adsets=ours,
            ads=[row for row in ads if row.adset_ref.id in group_ids],
        )
        logger.info(
            "watched %s: %s of %s groups run as our pages",
            ad_account.external_id,
            len(ours),
            len(adsets),
        )
        return summary
    finally:
        cache.delete(key)
