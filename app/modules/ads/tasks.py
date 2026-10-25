import logging
import uuid

from adskit.errors import RateLimited, TemporaryFailure
from celery import Task

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import MIRROR_SWEEP, REFRESH_QUEUE, SYNC_STARTED
from app.modules.ads.exceptions import (
    ConnectionUnusable,
    SyncAlreadyRunning,
    SyncFailed,
)
from app.modules.ads.models import LapseHold
from app.modules.ads.selectors import (
    frequently_swept_account_ids,
    lapse_candidates,
    library_swept_account_ids,
    nightly_swept_account_ids,
    open_holds,
)
from app.modules.ads.services import (
    SyncSummary,
    apply_change,
    apply_delete,
    drop_empty_campaign,
    note_sync_outcome,
    open_lapse_hold,
    resume_after_lapse,
    settle_lapse,
    sync_ad_account,
    sync_media,
    sync_owner_media,
    sync_recent_instagram,
)
from app.modules.integrations.models import AdAccount
from app.worker import celery_app, task_session

logger = logging.getLogger(__name__)
SWEEP_RETRIES = 5
SWEEP_RETRY_SECONDS = 60


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _counted(summary: SyncSummary) -> str:
    counted = f"{summary.campaigns}/{summary.adsets}/{summary.ads}/{summary.creatives}"
    return f"{counted} refused:{summary.refused}" if summary.refused else counted


# -- the mirror -----------------------------------------------------------------------


@celery_app.task(queue="sync", ignore_result=True)
def sync_ad_account_task(ad_account_id: str) -> str:
    with task_session() as db:
        pk = _uuid(ad_account_id)
        account = db.get(AdAccount, pk) if pk else None
        if account is None:
            return "gone"
        note_sync_outcome(
            sweep=MIRROR_SWEEP, ad_account_id=ad_account_id, outcome=SYNC_STARTED
        )
        try:
            summary = sync_ad_account(db, ad_account=account)
        except SyncAlreadyRunning:
            outcome = "busy"
        except ConnectionUnusable:
            logger.info("sync skipped for %s: connection unusable", account.external_id)
            outcome = "unusable"
        except SyncFailed as exc:
            outcome = f"failed:{exc.cause}" if exc.cause else "failed"
        else:
            outcome = _counted(summary)
        note_sync_outcome(
            sweep=MIRROR_SWEEP, ad_account_id=ad_account_id, outcome=outcome
        )
        return outcome


@celery_app.task(queue="sync", ignore_result=True)
def sync_all_accounts() -> int:
    with task_session() as db:
        accounts = frequently_swept_account_ids(db, now=utcnow())
    for account_id in accounts:
        sync_ad_account_task.delay(str(account_id))
    return len(accounts)


@celery_app.task(queue="sync", ignore_result=True)
def sync_every_account_nightly() -> int:
    with task_session() as db:
        accounts = nightly_swept_account_ids(db)
    for account_id in accounts:
        sync_ad_account_task.delay(str(account_id))
    return len(accounts)


# -- the media library ----------------------------------------------------------------


@celery_app.task(queue="sync", ignore_result=True)
def sync_media_task(ad_account_id: str) -> str:
    with task_session() as db:
        return sync_media(db, ad_account_id=ad_account_id)


@celery_app.task(queue="sync", ignore_result=True)
def sync_owner_media_task(owner_id: str) -> str:
    with task_session() as db:
        return sync_owner_media(db, owner_id=owner_id)


@celery_app.task(queue=REFRESH_QUEUE, ignore_result=True)
def sync_recent_instagram_task(page_id: str) -> str:
    with task_session() as db:
        return sync_recent_instagram(db, page_id=page_id)


@celery_app.task(queue="sync", ignore_result=True)
def sync_all_media() -> int:
    with task_session() as db:
        accounts = library_swept_account_ids(db, now=utcnow())
    for account_id in accounts:
        sync_media_task.delay(str(account_id))
    return len(accounts)


# -- changes on live adverts ----------------------------------------------------------


@celery_app.task(queue="agent")
def apply_change_task(log_id: str) -> str:
    with task_session() as db:
        return apply_change(db, log_id=log_id)


@celery_app.task(queue="agent")
def apply_delete_task(log_id: str) -> str:
    with task_session() as db:
        return apply_delete(db, log_id=log_id)


@celery_app.task(queue="agent")
def apply_swap_task(log_id: str) -> str:
    """Build the advert's next version and switch this one off. Never retried: every call creates."""
    from app.modules.ads.services.swap import apply_swap

    with task_session() as db:
        return apply_swap(db, log_id=log_id)


@celery_app.task(bind=True, queue="agent", max_retries=SWEEP_RETRIES)
def drop_empty_campaign_task(self: Task, log_id: str) -> str:
    try:
        with task_session() as db:
            return drop_empty_campaign(db, log_id=log_id)
    except (TemporaryFailure, RateLimited) as exc:
        if self.request.retries >= SWEEP_RETRIES:
            return "given up"
        raise self.retry(
            exc=exc, countdown=SWEEP_RETRY_SECONDS * (self.request.retries + 1)
        ) from exc


# -- a lapsed subscription ------------------------------------------------------------


@celery_app.task(queue="agent", ignore_result=True)
def sweep_lapsed_subscriptions() -> int:
    now = utcnow()
    with task_session() as db:
        owners = list(lapse_candidates(db, now=now))
        holds = [str(hold.id) for hold in open_holds(db)]
    for owner_id in owners:
        open_lapse_hold_task.delay(str(owner_id))
    for hold_id in holds:
        settle_lapse_hold_task.delay(hold_id)
    return len(owners) + len(holds)


@celery_app.task(queue="agent", ignore_result=True)
def open_lapse_hold_task(owner_id: str) -> str:
    with task_session() as db:
        pk = _uuid(owner_id)
        owner = db.get(User, pk) if pk else None
        if owner is None:
            return "gone"
        hold = open_lapse_hold(db, owner=owner, now=utcnow())
        return "held" if hold is not None else "nothing"


@celery_app.task(queue="agent", ignore_result=True)
def settle_lapse_hold_task(hold_id: str) -> str:
    with task_session() as db:
        pk = _uuid(hold_id)
        hold = db.get(LapseHold, pk) if pk else None
        if hold is None:
            return "gone"
        return settle_lapse(db, hold=hold, now=utcnow())


@celery_app.task(queue="agent", ignore_result=True)
def resume_after_payment_task(owner_id: str) -> str:
    from sqlalchemy import select

    with task_session() as db:
        pk = _uuid(owner_id)
        if pk is None:
            return "nothing"
        hold = db.scalars(
            select(LapseHold).where(
                LapseHold.owner_id == pk,
                LapseHold.resumed_at.is_(None),
                LapseHold.deleted_at.is_(None),
            )
        ).first()
        if hold is None:
            return "nothing"
        started = resume_after_lapse(db, hold=hold, now=utcnow())
        return "later" if started is None else "resumed"


@celery_app.task(queue="agent", ignore_result=True)
def fetch_preview_task(user_id: str, external_id: str, ad_format: str) -> str:
    """Ask the provider what one advert looks like and store the answer."""
    import uuid

    from app.modules.ads.exceptions import (
        ConnectionUnusable,
        PreviewUnavailable,
        UnknownTarget,
    )
    from app.modules.ads.services.settings import fetch_preview

    with task_session() as db:
        try:
            user = db.get(User, uuid.UUID(str(user_id)))
        except ValueError:
            user = None
        if user is None:
            return "gone"
        try:
            fetch_preview(db, user=user, external_id=external_id, ad_format=ad_format)
        except ConnectionUnusable:
            return "unusable"
        except (PreviewUnavailable, UnknownTarget):
            return "unavailable"
        db.commit()
        return "fetched"
