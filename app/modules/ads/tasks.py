import logging
import uuid

from adskit.errors import RateLimited, TemporaryFailure
from celery import Task

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    MIRROR_SWEEP,
    REFRESH_QUEUE,
    STILL_POLL_SECONDS,
    STILL_TRIES,
    SYNC_STARTED,
    UPLOAD_RETRIES,
    UPLOAD_RETRY_SECONDS,
)
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


@celery_app.task(queue="agent")
def apply_new_group_task(log_id: str) -> str:
    """Make a new group from one of the campaign's. Never retried: every call creates."""
    from app.modules.ads.services.additions import apply_new_group

    with task_session() as db:
        return apply_new_group(db, log_id=log_id)


@celery_app.task(queue="agent")
def apply_new_ad_task(log_id: str) -> str:
    """Make a new advert from one that works. Never retried: every call creates."""
    from app.modules.ads.services.additions import apply_new_ad

    with task_session() as db:
        return apply_new_ad(db, log_id=log_id)


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


# -- the launch ------------------------------------------------------------------------


@celery_app.task(queue="agent")
def build_draft_task(launch_id: str, run: str = "") -> str:
    """Ask Claude to prepare one campaign. No retry: every failure is on the row."""
    from app.modules.ads.services.proposal import build_draft

    with task_session() as db:
        return build_draft(db, launch_id=launch_id, run=run)


@celery_app.task(queue="agent")
def regenerate_section_task(launch_id: str, section: str) -> str:
    from app.modules.ads.services.sections import regenerate_section

    with task_session() as db:
        return regenerate_section(db, launch_id=launch_id, section=section)


@celery_app.task(queue="agent")
def rewrite_form_task(launch_id: str, depth: str) -> str:
    from app.modules.ads.services.forms import rewrite_form

    with task_session() as db:
        return rewrite_form(db, launch_id=launch_id, depth=depth)


@celery_app.task(queue="agent")
def suggest_options_task(launch_id: str, kind: str) -> str:
    from app.modules.ads.services.sections import suggest_options

    with task_session() as db:
        return suggest_options(db, launch_id=launch_id, kind=kind)


@celery_app.task(queue="agent")
def suggest_chat_questions_task(launch_id: str, token: str) -> str:
    from app.modules.ads.services.readings import suggest_chat_questions

    with task_session() as db:
        return suggest_chat_questions(db, launch_id=launch_id, token=token)


@celery_app.task(queue="agent")
def detect_goal_task(launch_id: str, token: str) -> str:
    from app.modules.ads.services.readings import detect_goal

    with task_session() as db:
        return detect_goal(db, launch_id=launch_id, token=token)


@celery_app.task(queue="agent")
def confirm_interests_task(launch_id: str) -> str:
    from app.modules.ads.services.interests import confirm_interests

    with task_session() as db:
        return confirm_interests(db, launch_id=launch_id)


@celery_app.task(queue="agent")
def resolve_locations_task(launch_id: str) -> str:
    from app.modules.ads.services.locations import resolve_locations

    with task_session() as db:
        return resolve_locations(db, launch_id=launch_id)


@celery_app.task(queue="agent")
def estimate_audience_task(launch_id: str) -> str:
    from app.modules.ads.services.interests import estimate_audience

    with task_session() as db:
        return estimate_audience(db, launch_id=launch_id)


@celery_app.task(queue="agent")
def create_campaign_task(launch_id: str) -> str:
    """Create one campaign at the provider, paused. No retry: see the service."""
    from app.modules.ads.services.creation import create_campaign

    with task_session() as db:
        return create_campaign(db, launch_id=launch_id)


@celery_app.task(queue=REFRESH_QUEUE, ignore_result=True)
def mirror_launch_task(launch_id: str) -> str:
    from app.modules.ads.services.creation import mirror_launch

    with task_session() as db:
        return mirror_launch(db, launch_id=launch_id)


@celery_app.task(queue="webhooks", ignore_result=True)
def auto_start_delivery_task(launch_id: str, tries: int = 0) -> str:
    """Switch on what the launch just created; re-queues itself while waiting."""
    from app.modules.ads.constants import AUTO_START_WAIT_SECONDS
    from app.modules.ads.services.creation import WAITING, auto_start_delivery

    with task_session() as db:
        outcome = auto_start_delivery(db, launch_id=launch_id, tries=tries)
    if outcome == WAITING:
        auto_start_delivery_task.apply_async(
            args=[launch_id, tries + 1], countdown=AUTO_START_WAIT_SECONDS
        )
    return outcome


@celery_app.task(queue="agent", ignore_result=True)
def clean_up_launch_task(launch_id: str) -> str:
    from app.modules.ads.services.launch import clean_up_launch

    with task_session() as db:
        return clean_up_launch(db, launch_id=launch_id)


@celery_app.task(queue="sync", ignore_result=True)
def sweep_stranded_launches_task() -> int:
    from app.modules.ads.services.rollback import sweep_stranded_launches

    with task_session() as db:
        return sweep_stranded_launches(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def rollback_stranded_launch_task(launch_id: str) -> str:
    from app.modules.ads.services.rollback import rollback_stranded_launch

    with task_session() as db:
        return rollback_stranded_launch(db, launch_id=launch_id)


@celery_app.task(queue="sync", ignore_result=True)
def close_stalled_changes_task() -> int:
    from app.modules.ads.services.manage import close_stalled_changes

    with task_session() as db:
        return close_stalled_changes(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def release_stalled_launches_task() -> int:
    from app.modules.ads.services.rollback import release_stalled_launches

    with task_session() as db:
        return release_stalled_launches(db)


@celery_app.task(queue="sync", ignore_result=True)
def check_owner_sites_task(owner_id: str) -> int:
    from app.modules.ads.services.preflight import check_sites

    with task_session() as db:
        return check_sites(db, owner_id=owner_id, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def check_all_sites_task() -> int:
    """Fan the nightly look out over everybody with a page to look at."""
    from app.modules.ads.selectors.actions import owners_to_check

    with task_session() as db:
        owners = owners_to_check(db)
    for owner_id in owners:
        check_owner_sites_task.delay(str(owner_id))
    return len(owners)


# -- the media library -----------------------------------------------------------------


@celery_app.task(
    bind=True, queue=REFRESH_QUEUE, ignore_result=True, max_retries=STILL_TRIES
)
def fetch_video_still_task(self: Task, asset_id: str, launch_id: str) -> str:
    """Ask Meta for a new video's first frame until it has one."""
    from app.modules.ads.exceptions import StillNotReady
    from app.modules.ads.services.library import (
        fetch_video_still,
        read_library_for_still,
    )

    with task_session() as db:
        try:
            return fetch_video_still(db, asset_id=asset_id, launch_id=launch_id)
        except StillNotReady as exc:
            if self.request.retries >= STILL_TRIES:
                return read_library_for_still(db, asset_id=asset_id)
            raise self.retry(exc=exc, countdown=STILL_POLL_SECONDS) from exc


@celery_app.task(
    bind=True, queue="upload", ignore_result=True, max_retries=UPLOAD_RETRIES
)
def upload_to_library_task(self: Task, creative_id: str, log_id: str) -> str:
    """Put one file in the library; an interrupted upload is carried on, not resent."""
    from app.modules.ads.exceptions import UploadInterrupted
    from app.modules.ads.services.library import give_up_on_upload, upload_to_library

    with task_session() as db:
        try:
            return upload_to_library(db, creative_id=creative_id, log_id=log_id)
        except UploadInterrupted as exc:
            if self.request.retries >= UPLOAD_RETRIES:
                return give_up_on_upload(
                    db, creative_id=creative_id, log_id=log_id, reason=str(exc)
                )
            raise self.retry(
                exc=exc, countdown=UPLOAD_RETRY_SECONDS * (self.request.retries + 1)
            ) from exc


@celery_app.task(queue="agent", ignore_result=True)
def delete_library_media_task(log_id: str) -> str:
    from app.modules.ads.services.library import delete_library_media

    with task_session() as db:
        return delete_library_media(db, log_id=log_id)


@celery_app.task(queue="sync", ignore_result=True)
def sweep_abandoned_uploads_task() -> int:
    from app.modules.ads.services.library import (
        drop_stale_partials,
        sweep_abandoned_uploads,
    )

    now = utcnow()
    drop_stale_partials(now=now)
    with task_session() as db:
        return sweep_abandoned_uploads(db, now=now)


# -- Google ----------------------------------------------------------------------------


@celery_app.task(queue="agent")
def prepare_google_launch_task(launch_id: str, run: str) -> str:
    from app.modules.ads.services.google import prepare_google_launch

    with task_session() as db:
        return prepare_google_launch(db, launch_id=launch_id, run=run)


@celery_app.task(queue="sync", ignore_result=True)
def refresh_google_volumes_task(launch_id: str) -> str:
    from app.modules.ads.services.google import refresh_google_volumes

    with task_session() as db:
        return refresh_google_volumes(db, launch_id=launch_id)


@celery_app.task(queue="agent")
def create_google_campaign_task(launch_id: str, run: str) -> str:
    from app.modules.ads.services.google import create_google_campaign

    with task_session() as db:
        return create_google_campaign(db, launch_id=launch_id, run=run)
