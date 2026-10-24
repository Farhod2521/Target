"""Reading accounts, pages, pixels, audiences and Instagram from the providers."""

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from adskit import AuthFailed, ProviderError, registry
from adskit.dto import AudienceDTO
from googleadskit import PROVIDER as GOOGLE
from googleadskit import (
    AdsClient,
    CustomerDTO,
    GoogleAdsError,
    list_accounts,
    translate_error,
)
from metaads import PROVIDER
from metaads.accounts import (
    list_ad_accounts,
    list_pages,
    list_pixels,
    may_advertise,
    may_run_ads,
    owes_payment,
    pixel_events,
)
from metaads.dto import AdAccountDTO, PageDTO, PixelDTO
from metaads.errors import MetaError
from metaads.instagram import read_instagram_profile
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.crypto import decrypt, encrypt, fingerprint
from app.common.db import on_commit, utcnow
from app.common.exceptions import DecryptionFailed
from app.modules.accounts.models import User
from app.modules.integrations.constants import (
    AUDIENCE_STALE_MINUTES,
    REFRESH_COOLDOWN_SECONDS,
    USABLE_CONNECTION_STATUSES,
    ConnectionStatus,
)
from app.modules.integrations.exceptions import (
    ConnectionTooNarrow,
    GoogleAdsUnavailable,
    GoogleNotConnected,
    InstagramNotGranted,
    NoActivePage,
    NoConnection,
    NoInstagram,
    RefreshTooSoon,
    UnknownPage,
)
from app.modules.integrations.models import (
    AdAccount,
    CustomAudience,
    PageAccount,
    PageInstagram,
    PixelAccount,
    ProviderConnection,
)
from app.modules.integrations.selectors import (
    active_ad_account,
    active_page,
    ad_accounts_of_other_owners,
    google_ads_on,
    google_connection,
    instagram_permission_missing,
    meta_connection,
    missing_scopes,
)
from app.modules.integrations.services.access import account_ref, port_for, token_for

logger = logging.getLogger(__name__)
MOST_PIXELS: Final = 5
_REVOKED_CODE: Final = "revoked"
EMPTY_PROFILE: Final[dict[str, Any]] = {
    "instagram_name": "",
    "instagram_biography": "",
    "instagram_website": "",
    "instagram_picture_url": "",
    "instagram_followers": None,
    "instagram_follows": None,
    "instagram_posts": None,
    "instagram_profile_synced_at": None,
}


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        return None


def _usable_token(connection: ProviderConnection | None) -> str | None:
    if connection is None or connection.status not in USABLE_CONNECTION_STATUSES:
        return None
    try:
        return decrypt(connection.token_encrypted)
    except DecryptionFailed:
        logger.exception("connection %s could not be decrypted", connection.id)
        return None


def sync_ad_accounts(db: Session, *, connection_id: object) -> str:
    connection = db.get(ProviderConnection, _uuid(connection_id))
    if connection is None:
        return "gone"
    token = _usable_token(connection)
    if token is None:
        return "unusable"
    try:
        found = list_ad_accounts(token=token)
    except MetaError as exc:
        logger.info("account list failed for connection %s: %s", connection.id, exc)
        return "failed"
    store_ad_accounts(db, connection=connection, accounts=found)
    db.commit()
    return str(len(found))


def _upsert_account(
    db: Session, *, provider: str, external_id: str, values: dict[str, Any]
) -> AdAccount:
    row = db.scalar(
        select(AdAccount).where(
            AdAccount.provider == provider, AdAccount.external_id == external_id
        )
    )
    if row is None:
        row = AdAccount(provider=provider, external_id=external_id)
        db.add(row)
    for name, value in values.items():
        setattr(row, name, value)
    return row


def store_ad_accounts(
    db: Session, *, connection: ProviderConnection, accounts: list[AdAccountDTO]
) -> None:
    taken = ad_accounts_of_other_owners(
        db,
        owner=connection.owner,
        provider=PROVIDER,
        external_ids=[account.id for account in accounts],
    )
    if taken:
        logger.error(
            "ad accounts held by another cabinet were not rewritten",
            extra={
                "connection": str(connection.id),
                "owner": str(connection.owner_id),
                "accounts": sorted(taken),
            },
        )
    for account in accounts:
        if account.id in taken:
            continue
        status = account.account_status
        _upsert_account(
            db,
            provider=PROVIDER,
            external_id=account.id,
            values={
                "owner_id": connection.owner_id,
                "connection_id": connection.id,
                "name": account.name,
                "business_external_id": account.business_id,
                "currency": account.currency,
                "timezone": account.timezone_name,
                "account_status": str(status),
                "disable_reason": str(account.disable_reason or ""),
                "may_advertise": may_run_ads(status) if status else None,
                "payment_due": owes_payment(status) if status else None,
                "min_daily_budget_minor": account.min_daily_budget_minor,
                "spend_cap_minor": account.spend_cap_minor,
                "amount_spent_minor": account.amount_spent_minor,
                "custom_audience_terms_accepted": account.custom_audience_terms_accepted,
            },
        )
    held = [
        {"external_id": account.id, "name": account.name}
        for account in accounts
        if account.id in taken
    ]
    if connection.ad_accounts_taken != held:
        connection.ad_accounts_taken = held
    db.flush()


def sync_pages(db: Session, *, connection_id: object) -> str:
    from app.modules.integrations.tasks import learn_instagram_grant_task

    connection = db.get(ProviderConnection, _uuid(connection_id))
    if connection is None:
        return "gone"
    token = _usable_token(connection)
    if token is None:
        return "unusable"
    try:
        found = list_pages(token=token)
    except MetaError as exc:
        logger.info("page list failed for connection %s: %s", connection.id, exc)
        return "failed"
    store_pages(db, connection=connection, pages=found)
    key = str(connection.id)
    on_commit(db, lambda: learn_instagram_grant_task.delay(key))
    adopt_only_page(db, connection=connection)
    db.commit()
    return str(len(found))


def _location(page: PageDTO) -> dict[str, object]:
    found = page.location
    if found is None:
        return {}
    return {
        "location_city": found.city,
        "location_city_key": str(found.city_id) if found.city_id else "",
        "location_lat": None
        if found.latitude is None
        else Decimal(str(found.latitude)),
        "location_lng": None
        if found.longitude is None
        else Decimal(str(found.longitude)),
    }


def store_pages(
    db: Session, *, connection: ProviderConnection, pages: list[PageDTO]
) -> None:
    now = utcnow()
    existing = {
        row.external_id: row
        for row in db.scalars(
            select(PageAccount).where(
                PageAccount.owner_id == connection.owner_id,
                PageAccount.provider == PROVIDER,
                PageAccount.external_id.in_([page.id for page in pages]),
            )
        )
    }
    before = {key: row.instagram_user_id for key, row in existing.items()}
    for page in pages:
        token = page.access_token
        moved = before.get(page.id, "") != page.instagram_id
        row = existing.get(page.id)
        if row is None:
            row = PageAccount(
                owner_id=connection.owner_id, provider=PROVIDER, external_id=page.id
            )
            db.add(row)
        values: dict[str, Any] = {
            "connection_id": connection.id,
            "name": page.name,
            "token_encrypted": encrypt(token),
            "token_fingerprint": fingerprint(token),
            "tasks": list(page.tasks),
            "may_advertise": may_advertise(page.tasks) if page.tasks else None,
            "leadgen_terms_accepted": page.leadgen_tos_accepted,
            "instagram_user_id": page.instagram_id,
            "instagram_username": page.instagram_username,
            **(EMPTY_PROFILE if moved else {}),
            **_location(page),
            "synced_at": now,
        }
        for name, value in values.items():
            setattr(row, name, value)
        db.flush()
        store_page_instagrams(db, page=row, found=page, now=now)
    if any(before.get(page.id, "") != page.instagram_id for page in pages):
        from app.modules.ads.tasks import sync_owner_media_task

        owner_id = str(connection.owner_id)
        on_commit(db, lambda: sync_owner_media_task.delay(owner_id))


def store_page_instagrams(
    db: Session, *, page: PageAccount, found: PageDTO, now: datetime
) -> None:
    seen: list[str] = []
    for account in found.instagram_accounts:
        seen.append(account.id)
        row = db.scalar(
            select(PageInstagram).where(
                PageInstagram.page_id == page.id,
                PageInstagram.instagram_user_id == account.id,
            )
        )
        if row is None:
            row = PageInstagram(page_id=page.id, instagram_user_id=account.id)
            db.add(row)
        row.owner_id = page.owner_id
        row.username = account.username
        row.is_linked = True
        row.synced_at = now
    db.execute(
        update(PageInstagram)
        .where(
            PageInstagram.page_id == page.id,
            PageInstagram.instagram_user_id.not_in(seen),
        )
        .values(is_linked=False, synced_at=now)
    )
    db.flush()


def clear_extra_instagrams(db: Session, *, page: PageAccount) -> None:
    db.execute(
        update(PageInstagram)
        .where(PageInstagram.page_id == page.id, PageInstagram.is_active.is_(True))
        .values(is_active=False)
    )


def adopt_only_page(
    db: Session, *, connection: ProviderConnection
) -> PageAccount | None:
    owner = connection.owner
    if active_page(db, owner=owner) is not None:
        return None
    found = list(
        db.scalars(
            select(PageAccount)
            .where(
                PageAccount.owner_id == owner.id,
                PageAccount.provider == connection.provider,
            )
            .limit(2)
        )
    )
    if len(found) != 1:
        return None
    from app.modules.integrations.services.cabinet import select_page

    return select_page(db, user=owner, external_id=found[0].external_id)


def sync_pixels(db: Session, *, ad_account_id: object) -> str:
    account = db.get(AdAccount, _uuid(ad_account_id))
    if account is None or account.provider != PROVIDER:
        return "gone"
    token = _usable_token(account.connection)
    if token is None:
        return "unusable"
    try:
        found = list_pixels(account_id=account.external_id, token=token)
    except MetaError as exc:
        logger.info("pixel list failed for %s: %s", account.external_id, exc)
        return "failed"
    _store_pixels(db, account=account, pixels=found)
    db.commit()
    return str(len(found))


def _store_pixels(db: Session, *, account: AdAccount, pixels: list[PixelDTO]) -> None:
    now = utcnow()
    stored: list[PixelAccount] = []
    for pixel in pixels:
        row = db.scalar(
            select(PixelAccount).where(
                PixelAccount.owner_id == account.owner_id,
                PixelAccount.provider == PROVIDER,
                PixelAccount.ad_account_id == account.id,
                PixelAccount.external_id == pixel.id,
            )
        )
        if row is None:
            row = PixelAccount(
                owner_id=account.owner_id,
                provider=PROVIDER,
                ad_account_id=account.id,
                external_id=pixel.id,
            )
            db.add(row)
        row.connection_id = account.connection_id
        row.name = pixel.name
        row.is_unavailable = pixel.is_unavailable
        row.last_fired_at = pixel.last_fired_time
        row.synced_at = now
        stored.append(row)
    db.flush()
    db.execute(
        delete(PixelAccount).where(
            PixelAccount.ad_account_id == account.id,
            PixelAccount.id.not_in([row.id for row in stored]),
        )
    )
    usable = [row for row in stored if not row.is_unavailable]
    if len(usable) == 1 and not any(row.is_active for row in stored):
        usable[0].is_active = True
    db.flush()


def sync_pixel_events(db: Session, *, ad_account_id: object) -> str:
    account = db.get(AdAccount, _uuid(ad_account_id))
    if account is None:
        return "gone"
    token = _usable_token(account.connection)
    if token is None:
        return "unusable"
    pixels = list(
        db.scalars(
            select(PixelAccount)
            .where(
                PixelAccount.owner_id == account.owner_id,
                PixelAccount.ad_account_id == account.id,
                PixelAccount.is_unavailable.is_(False),
            )
            .order_by(PixelAccount.is_active.desc(), PixelAccount.name)
            .limit(MOST_PIXELS)
        )
    )
    if not pixels:
        return "none"
    read = 0
    for pixel in pixels:
        try:
            found = pixel_events(pixel_id=pixel.external_id, token=token)
        except MetaError as exc:
            logger.info("pixel stats failed for %s: %s", pixel.external_id, exc)
            continue
        pixel.recent_events = [
            {"event": row.event, "count": row.count} for row in found
        ]
        pixel.events_synced_at = utcnow()
        read += 1
    db.commit()
    return str(read)


def sync_instagram_profile(db: Session, *, page: PageAccount, token: str) -> bool:
    asked = page.instagram_user_id
    if not asked:
        return False
    try:
        profile = read_instagram_profile(ig_user_id=asked, token=token)
    except MetaError as exc:
        logger.info(
            "instagram profile unread",
            extra={"page": page.external_id, "instagram": asked, "error": str(exc)},
        )
        return False
    fields: dict[str, Any] = {
        "instagram_name": profile.name,
        "instagram_biography": profile.biography,
        "instagram_website": profile.website,
        "instagram_picture_url": profile.profile_picture_url,
        "instagram_followers": profile.followers_count,
        "instagram_follows": profile.follows_count,
        "instagram_posts": profile.media_count,
        "instagram_profile_synced_at": utcnow(),
    }
    if profile.username:
        fields["instagram_username"] = profile.username
    stored = db.execute(
        update(PageAccount)
        .where(PageAccount.id == page.id, PageAccount.instagram_user_id == asked)
        .values(**fields)
    ).rowcount
    db.commit()
    logger.info(
        "instagram profile read",
        extra={"page": page.external_id, "instagram": asked, "stored": bool(stored)},
    )
    return bool(stored)


def sync_instagram_profile_by_id(db: Session, *, page_id: object) -> str:
    page = db.get(PageAccount, _uuid(page_id))
    if page is None:
        return "gone"
    if not page.instagram_user_id:
        return "unlinked"
    try:
        token = decrypt(page.token_encrypted)
    except DecryptionFailed:
        logger.exception("page %s could not be decrypted", page.id)
        return "unusable"
    stored = sync_instagram_profile(db, page=page, token=token)
    return "stored" if stored else "unread"


def sync_google_accounts(db: Session, *, connection_id: object) -> str:
    connection = db.get(ProviderConnection, _uuid(connection_id))
    if connection is None or connection.provider != GOOGLE:
        return "gone"
    stored = _usable_token(connection)
    if stored is None:
        return "unusable"
    try:
        access = registry.get(GOOGLE).connect.access_token(stored=stored)
        try:
            with AdsClient(token=access) as client:
                found = list_accounts(client)
        except GoogleAdsError as exc:
            raise translate_error(exc) from exc
    except AuthFailed:
        connection.status = ConnectionStatus.REVOKED
        connection.last_error_code = _REVOKED_CODE
        db.commit()
        return "revoked"
    except ProviderError as exc:
        logger.info(
            "google account list failed for connection %s: %s", connection.id, exc
        )
        return "failed"
    store_google_accounts(db, connection=connection, accounts=found)
    db.commit()
    return str(len(found))


def request_google_accounts(db: Session, *, user: User) -> None:
    from app.modules.integrations.tasks import sync_google_accounts_task

    if not google_ads_on(user=user):
        raise GoogleAdsUnavailable
    connection = google_connection(db, owner=user)
    if connection is None or connection.status not in USABLE_CONNECTION_STATUSES:
        raise GoogleNotConnected
    connection.updated_at = utcnow()
    key = str(connection.id)
    on_commit(db, lambda: sync_google_accounts_task.delay(key))


def store_google_accounts(
    db: Session, *, connection: ProviderConnection, accounts: list[CustomerDTO]
) -> None:
    taken = ad_accounts_of_other_owners(
        db,
        owner=connection.owner,
        provider=GOOGLE,
        external_ids=[account.id for account in accounts],
    )
    for account in accounts:
        if account.id in taken:
            continue
        _upsert_account(
            db,
            provider=GOOGLE,
            external_id=account.id,
            values={
                "owner_id": connection.owner_id,
                "connection_id": connection.id,
                "name": account.name,
                "currency": account.currency,
                "timezone": account.time_zone,
                "account_status": account.status,
                "may_advertise": account.can_advertise,
            },
        )
    held = [
        {"external_id": account.id, "name": account.name}
        for account in accounts
        if account.id in taken
    ]
    if connection.ad_accounts_taken != held:
        connection.ad_accounts_taken = held
    db.flush()


def request_audience_sync(db: Session, *, account: AdAccount) -> None:
    from app.modules.integrations.tasks import sync_audiences_task

    key = str(account.id)
    on_commit(db, lambda: sync_audiences_task.delay(key))


def refresh_if_stale(db: Session, *, account: AdAccount) -> bool:
    newest = db.scalar(
        select(CustomAudience.synced_at)
        .where(
            CustomAudience.owner_id == account.owner_id,
            CustomAudience.ad_account_id == account.id,
        )
        .order_by(CustomAudience.synced_at.desc().nulls_last())
        .limit(1)
    )
    if newest is not None and newest > utcnow() - timedelta(
        minutes=AUDIENCE_STALE_MINUTES
    ):
        return False
    request_audience_sync(db, account=account)
    return True


def refresh_targets_if_stale(db: Session, *, owner: User) -> bool:
    account = active_ad_account(db, owner=owner)
    if account is None:
        return False
    if not db.scalar(
        select(CustomAudience.id)
        .where(
            CustomAudience.owner_id == owner.id,
            CustomAudience.ad_account_id == account.id,
        )
        .limit(1)
    ):
        return False
    return refresh_if_stale(db, account=account)


def sync_audiences(db: Session, *, account: AdAccount, token: str = "") -> int:
    try:
        port = port_for(provider=account.provider)
        found = port.list_audiences(
            account=account_ref(account), token=token or token_for(ad_account=account)
        )
    except ProviderError as exc:
        logger.warning(
            "audience sync failed for account %s: %s", account.external_id, exc
        )
        return 0
    _store_audiences(db, account=account, audiences=found)
    db.commit()
    return len(found)


def _store_audiences(
    db: Session, *, account: AdAccount, audiences: list[AudienceDTO]
) -> None:
    now = utcnow()
    seen: set[str] = set()
    asked_for = set(
        db.scalars(
            select(CustomAudience.external_id).where(
                CustomAudience.owner_id == account.owner_id,
                CustomAudience.ad_account_id == account.id,
                CustomAudience.source_kind != "",
            )
        )
    )
    for dto in audiences:
        fields: dict[str, object] = {
            "owner_id": account.owner_id,
            "ad_account_id": account.id,
            "name": dto.name,
            "description": dto.description,
            "subtype_raw": dto.subtype_raw,
            "accepts_members": dto.accepts_members,
            "can_seed": dto.can_seed,
            "approximate_count_lower": dto.approximate_count_lower,
            "approximate_count_upper": dto.approximate_count_upper,
            "processing_code": dto.processing.code,
            "processing_text": dto.processing.description,
            "readiness_code": dto.readiness.code,
            "readiness_text": dto.readiness.description,
            "is_ready": dto.is_ready,
            "customer_file_source": dto.customer_file_source,
            "rule_raw": dto.rule_raw,
            "lookalike_raw": dto.lookalike_raw,
            "retention_days": dto.retention_days,
            "provider_created_at": dto.created_time,
            "provider_updated_at": dto.updated_time,
            "synced_at": now,
        }
        if dto.ref.id in asked_for:
            del fields["retention_days"]
        upsert_audience(
            db, provider=dto.ref.provider, external_id=dto.ref.id, values=fields
        )
        seen.add(dto.ref.id)
    retired = db.execute(
        update(CustomAudience)
        .where(
            CustomAudience.owner_id == account.owner_id,
            CustomAudience.ad_account_id == account.id,
            CustomAudience.external_id.not_in(seen),
            CustomAudience.is_ready.is_(True),
        )
        .values(
            is_ready=False,
            approximate_count_lower=0,
            approximate_count_upper=0,
            readiness_code="",
            readiness_text="",
            updated_at=now,
        )
    ).rowcount
    if retired:
        logger.info(
            "audience sync retired %s rows on account %s", retired, account.external_id
        )


def upsert_audience(
    db: Session, *, provider: str, external_id: str, values: dict[str, object]
) -> CustomAudience:
    row = db.scalar(
        select(CustomAudience).where(
            CustomAudience.provider == provider,
            CustomAudience.external_id == external_id,
        )
    )
    if row is None:
        row = CustomAudience(provider=provider, external_id=external_id)
        db.add(row)
    for name, value in values.items():
        setattr(row, name, value)
    db.flush()
    return row


def _usable_connection(db: Session, *, owner: User) -> ProviderConnection:
    connection = meta_connection(db, owner=owner)
    if connection is None or connection.status not in USABLE_CONNECTION_STATUSES:
        raise NoConnection
    return connection


def _spend(*, owner: User, question: str) -> None:
    if not cache.add(
        f"integrations:recheck:{question}:{owner.id}", "1", REFRESH_COOLDOWN_SECONDS
    ):
        raise RefreshTooSoon


def refresh_accounts(db: Session, *, user: User) -> None:
    from app.modules.integrations.tasks import sync_ad_accounts_task, sync_pages_task

    connection = _usable_connection(db, owner=user)
    _spend(owner=user, question="accounts")
    key = str(connection.id)
    on_commit(db, lambda: sync_ad_accounts_task.delay(key))
    on_commit(db, lambda: sync_pages_task.delay(key))


def recheck_leads(db: Session, *, user: User) -> None:
    from app.modules.integrations.tasks import sync_pages_task
    from app.modules.leads.tasks import subscribe_page_task

    connection = _usable_connection(db, owner=user)
    page = active_page(db, owner=user)
    if page is None:
        raise NoActivePage
    absent = missing_scopes(db, owner=user)
    if absent:
        raise ConnectionTooNarrow(absent)
    _spend(owner=user, question="leads")
    page_id, connection_id = str(page.id), str(connection.id)
    on_commit(db, lambda: subscribe_page_task.delay(page_id))
    on_commit(db, lambda: sync_pages_task.delay(connection_id))


def connect_page_leads(db: Session, *, user: User, page_id: str) -> PageAccount:
    from app.modules.leads.tasks import reconcile_page_task, subscribe_page_task

    connection = _usable_connection(db, owner=user)
    key = _uuid(page_id)
    page = db.scalar(
        select(PageAccount).where(
            PageAccount.owner_id == user.id, PageAccount.id == key
        )
    )
    if page is None or page.connection_id != connection.id:
        raise UnknownPage
    absent = missing_scopes(db, owner=user)
    if absent:
        raise ConnectionTooNarrow(absent)
    _spend(owner=user, question=f"leads:{page.id}")
    page_key = str(page.id)
    on_commit(db, lambda: subscribe_page_task.delay(page_key))
    on_commit(db, lambda: reconcile_page_task.delay(page_key))
    return page


def refresh_instagram_profile(db: Session, *, user: User) -> None:
    from app.modules.integrations.tasks import sync_instagram_profile_task

    _usable_connection(db, owner=user)
    page = active_page(db, owner=user)
    if page is None:
        raise NoActivePage
    if not page.has_instagram:
        raise NoInstagram
    if instagram_permission_missing(db, owner=user):
        raise InstagramNotGranted
    _spend(owner=user, question="instagram")
    key = str(page.id)
    on_commit(db, lambda: sync_instagram_profile_task.delay(key))
