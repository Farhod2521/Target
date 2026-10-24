import logging
import uuid
from datetime import timedelta

from app.common.config import settings
from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.ads.constants import FIGURES_SWEEP, SYNC_STARTED, TODAY_SWEEP
from app.modules.ads.exceptions import (
    ConnectionUnusable,
    SyncAlreadyRunning,
    SyncFailed,
)
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import RETRY_SPREAD_SECONDS
from app.modules.metrics.exceptions import AccountUnreadable
from app.modules.metrics.services import (
    TEMPORARY,
    ad_retention_floor,
    chase_missing_leads,
    purge_ad_metrics,
    purge_breakdowns,
    report_unfinished_figures,
    request_backfill,
    retention_floor,
    sync_all_observed,
    sync_insights,
    sync_observed,
    sync_today,
)
from app.worker import celery_app, task_session

logger = logging.getLogger(__name__)


def _account(db: object, ad_account_id: str) -> AdAccount | None:
    try:
        return db.get(AdAccount, uuid.UUID(str(ad_account_id)))  # type: ignore[attr-defined]
    except ValueError:
        return None


def _note(sweep: str, ad_account_id: str, word: str) -> str:
    from app.modules.ads.services import note_sync_outcome

    note_sync_outcome(sweep=sweep, ad_account_id=ad_account_id, outcome=word)
    return word


def _again(ad_account_id: str, *, attempt: int, word: str) -> str:
    minutes = int(settings.metrics_retry_minutes)
    if attempt >= 1 or minutes <= 0:
        return word
    countdown = minutes * 60 + uuid.UUID(ad_account_id).int % RETRY_SPREAD_SECONDS
    sync_insights_task.apply_async(
        args=[ad_account_id], kwargs={"attempt": attempt + 1}, countdown=countdown
    )
    return f"{word} again_in:{countdown}s"


@celery_app.task(queue="sync", ignore_result=True)
def sync_insights_task(ad_account_id: str, attempt: int = 0) -> str:
    with task_session() as db:
        account = _account(db, ad_account_id)
        if account is None:
            return "gone"
        _note(FIGURES_SWEEP, ad_account_id, SYNC_STARTED)
        try:
            summary = sync_insights(db, ad_account=account)
        except SyncAlreadyRunning:
            word = _again(ad_account_id, attempt=attempt, word="already_running")
            return _note(FIGURES_SWEEP, ad_account_id, word)
        except ConnectionUnusable:
            return _note(FIGURES_SWEEP, ad_account_id, "connection_unusable")
        except SyncFailed as exc:
            word = f"provider_failed:{exc.cause}" if exc.cause else "provider_failed"
            if exc.cause == TEMPORARY:
                word = _again(ad_account_id, attempt=attempt, word=word)
            return _note(FIGURES_SWEEP, ad_account_id, word)
        counted = f"rows:{summary.rows} segments:{summary.segment_rows} calls:{summary.calls}"
        if summary.complete:
            return _note(FIGURES_SWEEP, ad_account_id, counted)
        word = f"{counted} stopped:{summary.stopped_at} by:{summary.stopped_by}"
        if summary.stopped_by == TEMPORARY:
            word = _again(ad_account_id, attempt=attempt, word=word)
        return _note(FIGURES_SWEEP, ad_account_id, word)


@celery_app.task(queue="sync", ignore_result=True)
def sync_today_task(ad_account_id: str, people_after_seconds: int = 0) -> str:
    _note(TODAY_SWEEP, ad_account_id, SYNC_STARTED)
    with task_session() as db:
        word = _read_today(db, ad_account_id, people_after_seconds=people_after_seconds)
    return _note(TODAY_SWEEP, ad_account_id, word)


def _read_today(db: object, ad_account_id: str, *, people_after_seconds: int) -> str:
    account = _account(db, ad_account_id)
    if account is None:
        return "gone"
    try:
        summary = sync_today(
            db,  # type: ignore[arg-type]
            ad_account=account,
            people_after=timedelta(seconds=people_after_seconds) if people_after_seconds else None,
        )
    except SyncAlreadyRunning:
        return "already_running"
    except ConnectionUnusable:
        return "connection_unusable"
    if summary.unread:
        asked = request_backfill(db, ad_account=account)  # type: ignore[arg-type]
        db.commit()  # type: ignore[attr-defined]
        return f"no_history:{','.join(summary.unread)} backfill:{asked}"
    chased = chase_missing_leads(db, ad_account=account)  # type: ignore[arg-type]
    tail = f" chased:{chased}" if chased else ""
    if summary.complete:
        return f"rows:{summary.rows}{tail}"
    return f"rows:{summary.rows} stopped:{summary.stopped_at} by:{summary.stopped_by}{tail}"


@celery_app.task(queue="sync", ignore_result=True)
def sync_today_metrics() -> str:
    from app.modules.ads.selectors import frequently_swept_account_ids

    with task_session() as db:
        accounts = frequently_swept_account_ids(db, now=utcnow())
    for account_id in accounts:
        sync_today_task.delay(str(account_id))
    return f"queued:{len(accounts)}"


@celery_app.task(queue="sync", ignore_result=True)
def sync_all_metrics() -> str:
    from app.modules.ads.selectors import nightly_due_account_ids
    from app.modules.integrations.constants import NIGHT_FIGURES_HOUR

    now = utcnow()
    with task_session() as db:
        accounts = nightly_due_account_ids(db, now=now, hour=NIGHT_FIGURES_HOUR)
        for account_id in accounts:
            sync_insights_task.delay(str(account_id))
        observed = sync_all_observed(db, now=now, hour=NIGHT_FIGURES_HOUR)
    return f"queued:{len(accounts)}:observed:{observed}"


@celery_app.task(queue="sync", ignore_result=True)
def sync_observed_task(ad_account_id: str) -> str:
    from app.modules.ads.services import sync_watched_account

    with task_session() as db:
        account = _account(db, ad_account_id)
        if account is None:
            return "gone"
        try:
            mirrored = str(sync_watched_account(db, ad_account=account).campaigns)
        except SyncAlreadyRunning:
            mirrored = "already_running"
        except AccountUnreadable:
            mirrored = "unreadable"
        except ConnectionUnusable:
            mirrored = "connection_unusable"
        except SyncFailed:
            mirrored = "provider_failed"
        try:
            summary = sync_observed(db, ad_account=account, now=utcnow())
        except SyncAlreadyRunning:
            return "already_running"
        except AccountUnreadable:
            return "unreadable"
        except ConnectionUnusable:
            return "connection_unusable"
        except SyncFailed:
            return "provider_failed"
        kept = f"mirror:{mirrored} rows:{summary.rows} of:{summary.offered}"
        return kept if summary.still_delivering else f"{kept} quiet"


@celery_app.task(queue="sync", ignore_result=True)
def sync_observed_metrics() -> str:
    with task_session() as db:
        return f"queued:{sync_all_observed(db, now=utcnow())}"


@celery_app.task(queue="sync", ignore_result=True)
def purge_old_figures_task() -> str:
    purge_breakdowns_task.delay()
    purge_ad_metrics_task.delay()
    return "queued"


@celery_app.task(queue="sync", ignore_result=True)
def purge_breakdowns_task() -> str:
    with task_session() as db:
        removed = purge_breakdowns(db, before=retention_floor(today=localtime(utcnow()).date()))
    return f"purged:{removed}"


@celery_app.task(queue="sync", ignore_result=True)
def purge_ad_metrics_task() -> str:
    with task_session() as db:
        removed = purge_ad_metrics(db, before=ad_retention_floor(today=localtime(utcnow()).date()))
    return f"purged:{removed}"


@celery_app.task(queue="sync", ignore_result=True)
def report_unfinished_figures_task() -> int:
    with task_session() as db:
        return report_unfinished_figures(db, now=utcnow())
