import logging
import uuid
from datetime import timedelta

from celery import chain
from metaads import PROVIDER
from sqlalchemy import or_, select

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.integrations.constants import (
    REFRESH_WINDOW_DAYS,
    USABLE_CONNECTION_STATUSES,
    ConnectionStatus,
)
from app.modules.integrations.models import AdAccount, PixelAccount, ProviderConnection
from app.modules.integrations.selectors import accounts_holding_audiences
from app.modules.integrations.services import (
    discover_all_lead_accounts,
    discover_lead_accounts,
    learn_instagram_grant,
    refresh_connection,
    report_stale_mirror,
    sync_ad_accounts,
    sync_audiences,
    sync_google_accounts,
    sync_instagram_profile_by_id,
    sync_pages,
    sync_pixel_events,
    sync_pixels,
    verify_connection,
)
from app.worker import celery_app, task_session

logger = logging.getLogger(__name__)


@celery_app.task(queue="sync", ignore_result=True)
def refresh_expiring_tokens() -> int:
    with task_session() as db:
        for connection in list(
            db.scalars(
                select(ProviderConnection).where(
                    ProviderConnection.provider == PROVIDER,
                    ProviderConnection.status == ConnectionStatus.ACTIVE,
                    ProviderConnection.expires_at.is_(None),
                )
            )
        ):
            verify_connection(db, connection=connection)
        deadline = utcnow() + timedelta(days=REFRESH_WINDOW_DAYS)
        due = list(
            db.scalars(
                select(ProviderConnection).where(
                    ProviderConnection.provider == PROVIDER,
                    ProviderConnection.status == ConnectionStatus.ACTIVE,
                    ProviderConnection.expires_at.is_not(None),
                    ProviderConnection.expires_at <= deadline,
                )
            )
        )
        refreshed = sum(
            1
            for connection in due
            if refresh_connection(db, connection=connection).status
            == ConnectionStatus.ACTIVE
        )
    logger.info("token refresh: %s of %s connections renewed", refreshed, len(due))
    return refreshed


@celery_app.task(queue="sync", ignore_result=True)
def sync_pixels_task(ad_account_id: str) -> str:
    with task_session() as db:
        return sync_pixels(db, ad_account_id=ad_account_id)


@celery_app.task(queue="sync", ignore_result=True)
def sync_pixel_events_task(ad_account_id: str) -> str:
    with task_session() as db:
        return sync_pixel_events(db, ad_account_id=ad_account_id)


@celery_app.task(queue="sync", ignore_result=True)
def sync_all_pixel_events() -> int:
    with task_session() as db:
        accounts = list(
            db.scalars(
                select(AdAccount.id)
                .join(
                    ProviderConnection, ProviderConnection.id == AdAccount.connection_id
                )
                .outerjoin(PixelAccount, PixelAccount.ad_account_id == AdAccount.id)
                .where(
                    or_(AdAccount.is_active.is_(True), PixelAccount.id.is_not(None)),
                    ProviderConnection.status.in_(USABLE_CONNECTION_STATUSES),
                )
                .distinct()
            )
        )
    for account_id in accounts:
        chain(
            sync_pixels_task.si(str(account_id)),
            sync_pixel_events_task.si(str(account_id)),
        ).delay()
    logger.info("pixel event sweep: %s accounts queued", len(accounts))
    return len(accounts)


@celery_app.task(queue="sync", ignore_result=True)
def sync_ad_accounts_task(connection_id: str) -> str:
    with task_session() as db:
        return sync_ad_accounts(db, connection_id=connection_id)


@celery_app.task(queue="sync", ignore_result=True)
def sync_google_accounts_task(connection_id: str) -> str:
    with task_session() as db:
        return sync_google_accounts(db, connection_id=connection_id)


@celery_app.task(queue="sync", ignore_result=True)
def sync_pages_task(connection_id: str) -> str:
    with task_session() as db:
        return sync_pages(db, connection_id=connection_id)


@celery_app.task(queue="sync", ignore_result=True)
def sync_instagram_profile_task(page_id: str) -> str:
    with task_session() as db:
        return sync_instagram_profile_by_id(db, page_id=page_id)


@celery_app.task(queue="sync", ignore_result=True)
def sync_audiences_task(ad_account_id: str) -> str:
    with task_session() as db:
        account = db.get(AdAccount, uuid.UUID(ad_account_id))
        if account is None:
            return "gone"
        return str(sync_audiences(db, account=account))


@celery_app.task(queue="sync", ignore_result=True)
def sync_all_audiences() -> int:
    with task_session() as db:
        accounts = accounts_holding_audiences(db)
    for account_id in accounts:
        sync_audiences_task.delay(str(account_id))
    logger.info("audience sweep: %s accounts queued", len(accounts))
    return len(accounts)


@celery_app.task(queue="sync", ignore_result=True)
def report_stale_mirror_task() -> int:
    with task_session() as db:
        return report_stale_mirror(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def discover_lead_accounts_task(owner_id: str) -> int:
    with task_session() as db:
        owner = db.get(User, uuid.UUID(owner_id))
        if owner is None:
            return 0
        return discover_lead_accounts(db, owner=owner, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def discover_all_lead_accounts_task() -> int:
    with task_session() as db:
        return discover_all_lead_accounts(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def learn_instagram_grant_task(connection_id: str) -> str:
    with task_session() as db:
        return learn_instagram_grant(db, connection_id=connection_id)
