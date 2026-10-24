"""Finding the accounts a customer advertises from without having connected them."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from adskit import ExternalRef, registry
from adskit.dto import AdDTO, AdSetDTO
from adskit.errors import ProviderError
from metaads import PROVIDER
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common import throttle
from app.common.crypto import decrypt
from app.common.db import on_commit
from app.common.exceptions import DecryptionFailed
from app.modules.accounts.models import User
from app.modules.integrations.constants import (
    BUSINESS_LOOKUP_SECONDS,
    MIRROR_NIGHTLY_STALE_MINUTES,
    MIRROR_STALE_MINUTES,
    NIGHT_LEADS_HOUR,
    USABLE_CONNECTION_STATUSES,
)
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.integrations.selectors import (
    OBSERVE_DAYS,
    enabled_pages,
    mirror_age,
    owners_at_hour,
)
from core.ads import page_of_post, page_of_promoted

logger = logging.getLogger(__name__)
ACCOUNT_LEVEL = "account"
EVIDENCE_DAYS = 14
MAX_ADSETS = 5
MAX_CANDIDATES = 10
LOOKUP_BUCKET = "integrations:business-open"
LOOKUP_LIMIT = 1


@dataclass(frozen=True, slots=True)
class AccountAdvertising:
    adsets: frozenset[str] = frozenset()
    pages: frozenset[str] = frozenset()


def _reader(*, account: AdAccount) -> tuple[ExternalRef, str] | None:
    try:
        token = decrypt(account.connection.token_encrypted)
    except DecryptionFailed:
        logger.exception("connection %s could not be decrypted", account.connection_id)
        return None
    return (
        ExternalRef(
            provider=account.provider, level=ACCOUNT_LEVEL, id=account.external_id
        ),
        token,
    )


def _adsets(*, account: AdAccount) -> list[AdSetDTO] | None:
    read = _reader(account=account)
    if read is None:
        return None
    ref, token = read
    try:
        return registry.get(account.provider).campaigns.list_adsets(
            account=ref, token=token
        )
    except ProviderError as exc:
        logger.info("could not read groups of %s: %s", account.external_id, exc)
        return None


def _ads(*, account: AdAccount) -> list[AdDTO] | None:
    read = _reader(account=account)
    if read is None:
        return None
    ref, token = read
    try:
        return registry.get(account.provider).campaigns.list_ads(
            account=ref, token=token
        )
    except ProviderError as exc:
        logger.info("could not read adverts of %s: %s", account.external_id, exc)
        return None


def declared_advertising(*, account: AdAccount) -> AccountAdvertising | None:
    rows = _adsets(account=account)
    if rows is None:
        return None
    return AccountAdvertising(
        adsets=frozenset(row.ref.id for row in rows),
        pages=frozenset(
            page for row in rows if (page := page_of_promoted(row.promoted_object_raw))
        ),
    )


def advertised_pages(*, account: AdAccount) -> frozenset[str] | None:
    rows = _ads(account=account)
    if rows is None:
        return None
    found: set[str] = set()
    for row in rows:
        creative = row.creative
        if creative is None:
            continue
        page = creative.page_id or page_of_post(creative.post_external_id)
        if page:
            found.add(page)
    return frozenset(found)


def note_lead_sighting(db: Session, *, account: AdAccount, at: datetime) -> None:
    db.execute(
        update(AdAccount).where(AdAccount.id == account.id).values(leads_seen_at=at)
    )


def discover_lead_accounts(db: Session, *, owner: User, now: datetime) -> int:
    from app.modules.leads.selectors import unpriced_adset_ids

    adsets = unpriced_adset_ids(
        db, owner=owner, since=now - timedelta(days=EVIDENCE_DAYS), limit=MAX_ADSETS
    )
    pages = {page.external_id for page in enabled_pages(db, owner=owner)}
    if not adsets and not pages:
        return 0
    candidates = list(
        db.scalars(
            select(AdAccount)
            .join(ProviderConnection, ProviderConnection.id == AdAccount.connection_id)
            .where(
                AdAccount.owner_id == owner.id,
                AdAccount.provider == PROVIDER,
                AdAccount.is_active.is_(False),
                ProviderConnection.status.in_(USABLE_CONNECTION_STATUSES),
            )
            .order_by(AdAccount.leads_seen_at.desc().nulls_last(), AdAccount.name)
            .limit(MAX_CANDIDATES)
        )
    )
    if not candidates:
        logger.info(
            "advertising with no candidate account",
            extra={"owner": str(owner.id), "adsets": len(adsets)},
        )
        return 0
    named = 0
    for account in candidates:
        if not adsets and not pages:
            break
        seen_at = account.leads_seen_at
        if (
            seen_at is not None
            and seen_at >= now - timedelta(days=OBSERVE_DAYS)
            and not adsets
        ):
            continue
        matched, seen = _evidence(account=account, adsets=tuple(adsets), pages=pages)
        if not matched and not seen:
            continue
        note_lead_sighting(db, account=account, at=now)
        named += 1
        logger.info(
            "advertising placed in an account nobody connected",
            extra={
                "owner": str(owner.id),
                "account_external_id": account.external_id,
                "adsets": list(matched),
                "pages": sorted(seen),
            },
        )
        adsets = tuple(item for item in adsets if item not in matched)
    db.commit()
    return named


def _evidence(
    *, account: AdAccount, adsets: tuple[str, ...], pages: set[str]
) -> tuple[tuple[str, ...], set[str]]:
    found = declared_advertising(account=account)
    if found is None:
        return (), set()
    matched = tuple(item for item in adsets if item in found.adsets)
    seen = found.pages & pages
    if matched or seen:
        return matched, seen
    return (), set(advertised_pages(account=account) or frozenset()) & pages


def discover_all_lead_accounts(db: Session, *, now: datetime) -> int:
    from app.modules.billing.selectors import subscribed_owner_ids
    from app.modules.integrations.tasks import discover_lead_accounts_task

    candidates = db.scalars(
        select(AdAccount.owner_id)
        .join(ProviderConnection, ProviderConnection.id == AdAccount.connection_id)
        .where(
            AdAccount.provider == PROVIDER,
            AdAccount.is_active.is_(False),
            AdAccount.owner_id.in_(subscribed_owner_ids(db)),
            ProviderConnection.status.in_(USABLE_CONNECTION_STATUSES),
        )
        .distinct()
    ).all()
    owners = owners_at_hour(db, owner_ids=candidates, now=now, hour=NIGHT_LEADS_HOUR)
    for owner_id in owners:
        discover_lead_accounts_task.delay(str(owner_id))
    return len(owners)


def report_stale_mirror(db: Session, *, now: datetime) -> int:
    age = mirror_age(db, now=now)
    if not age.stale:
        return 0
    logger.error(
        "mirror has stopped moving",
        extra={
            "stale": age.stale,
            "watched": age.watched,
            "awake": age.awake,
            "oldest_minutes": age.oldest_minutes,
            "floor_minutes": MIRROR_STALE_MINUTES,
            "nightly_floor_minutes": MIRROR_NIGHTLY_STALE_MINUTES,
            "accounts": list(age.external_ids),
            "outcomes": age.outcomes,
        },
    )
    return age.stale


def learn_business_on_open(db: Session, *, ad_account: AdAccount) -> bool:
    from app.modules.integrations.tasks import sync_ad_accounts_task

    if ad_account.business_external_id or not ad_account.connection_id:
        return False
    if not throttle.hit(
        bucket=LOOKUP_BUCKET,
        key=str(ad_account.connection_id),
        limit=LOOKUP_LIMIT,
        window_seconds=BUSINESS_LOOKUP_SECONDS,
    ):
        return False
    key = str(ad_account.connection_id)
    on_commit(db, lambda: sync_ad_accounts_task.delay(key))
    return True
