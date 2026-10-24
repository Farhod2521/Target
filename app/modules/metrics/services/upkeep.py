"""Asking for fresh figures, chasing missing leads, purging old rows, the cards."""

import logging
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.common import throttle
from app.common.cache import cache
from app.common.db import on_commit, utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    FIGURES_SWEEP,
    REFRESH_QUEUE,
    SYNC_QUEUED,
    SYNC_STARTED,
    TODAY_SWEEP,
)
from app.modules.ads.exceptions import NoAdAccount
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.models import AdAccount, PageAccount, ProviderConnection
from app.modules.metrics.constants import (
    AD_METRICS_RETENTION_DAYS,
    AUTO_REFRESH_COOLING_MINUTES,
    BACKFILL_RETRY_HOURS,
    CHASE_LEADS_KEY,
    CHASE_LEADS_SECONDS,
    FIGURES_NEW_ACCOUNT_HOURS,
    FIGURES_REPORT_SAMPLE,
    PEOPLE_ASKED_SECONDS,
    PURGE_BATCH,
    MetricLevel,
)
from app.modules.metrics.models import MetricPreference, MetricsBreakdown, MetricsDaily
from app.modules.metrics.selectors.facts import has_cooled, last_synced_at
from app.modules.metrics.selectors.lead_gap import short_pages_today
from core.metrics import CardKey, chosen_keys

logger = logging.getLogger(__name__)
BACKFILL_BUCKET = "metrics:backfill"
OPEN_BUCKET = "metrics:today-open"
OPEN_LIMIT = 1
FAILED_OUTCOMES = ("provider_failed", "connection_unusable")


def request_backfill(db: Session, *, ad_account: AdAccount) -> bool:
    from app.modules.metrics.tasks import sync_insights_task

    if not throttle.hit(
        bucket=BACKFILL_BUCKET,
        key=f"{ad_account.provider}:{ad_account.external_id}",
        limit=1,
        window_seconds=BACKFILL_RETRY_HOURS * 60 * 60,
    ):
        return False
    account_id = str(ad_account.id)
    on_commit(db, lambda: sync_insights_task.delay(account_id))
    return True


def _queue_today(db: Session, account: AdAccount) -> None:
    from app.modules.ads.services import note_sync_outcome
    from app.modules.metrics.tasks import sync_today_task

    account_id = str(account.id)
    note_sync_outcome(sweep=TODAY_SWEEP, ad_account_id=account_id, outcome=SYNC_QUEUED)
    on_commit(
        db,
        lambda: sync_today_task.apply_async(
            (account_id,), kwargs={"people_after_seconds": PEOPLE_ASKED_SECONDS}, queue=REFRESH_QUEUE
        ),
    )


def _open_account(db: Session, *, user: User, account: AdAccount) -> bool:
    if not has_cooled(synced_at=last_synced_at(db, owner=user, account=account)):
        return False
    return throttle.hit(
        bucket=OPEN_BUCKET,
        key=f"{account.provider}:{account.external_id}",
        limit=OPEN_LIMIT,
        window_seconds=AUTO_REFRESH_COOLING_MINUTES * 60,
    )


def request_refresh(db: Session, *, user: User) -> None:
    from app.modules.metrics.selectors.scope import page_campaigns

    accounts = page_campaigns(db, owner=user).accounts
    if not accounts:
        raise NoAdAccount
    for account in accounts:
        _queue_today(db, account)


def refresh_on_open(db: Session, *, user: User) -> bool:
    from app.modules.metrics.selectors.scope import page_campaigns

    queued = False
    for account in page_campaigns(db, owner=user).accounts:
        if _open_account(db, user=user, account=account):
            _queue_today(db, account)
            queued = True
    return queued


def refresh_account_on_open(db: Session, *, user: User, account: AdAccount) -> bool:
    if not _open_account(db, user=user, account=account):
        return False
    _queue_today(db, account)
    return True


def chase_missing_leads(db: Session, *, ad_account: AdAccount) -> int:
    """Ask the lead reconciler for pages Meta counted more of today than we hold."""
    from app.modules.leads.tasks import reconcile_page_task

    ids = short_pages_today(db, owner=ad_account.owner, account=ad_account, now=utcnow())
    if not ids:
        return 0
    pages = db.scalars(
        select(PageAccount)
        .join(ProviderConnection, ProviderConnection.id == PageAccount.connection_id)
        .where(
            PageAccount.owner_id == ad_account.owner_id,
            PageAccount.external_id.in_(ids),
            PageAccount.leadgen_subscribed.is_(True),
            ProviderConnection.status.in_([str(s) for s in USABLE_CONNECTION_STATUSES]),
        )
    )
    queued = 0
    for page in pages:
        if cache.add(CHASE_LEADS_KEY.format(page=page.id), "1", CHASE_LEADS_SECONDS):
            reconcile_page_task.delay(str(page.id))
            queued += 1
    return queued


def ad_retention_floor(*, today: date) -> date:
    return today - timedelta(days=AD_METRICS_RETENTION_DAYS - 1)


def _purge(db: Session, model: object, *where: object) -> int:
    removed = 0
    while True:
        keys = list(db.scalars(select(model.id).where(*where).limit(PURGE_BATCH)))  # type: ignore[attr-defined]
        if not keys:
            break
        removed += db.execute(delete(model).where(model.id.in_(keys))).rowcount  # type: ignore[attr-defined, arg-type]
        db.commit()
    return removed


def purge_ad_metrics(db: Session, *, before: date) -> int:
    removed = _purge(
        db, MetricsDaily, MetricsDaily.level == str(MetricLevel.AD), MetricsDaily.date < before
    )
    if removed:
        logger.info("purged %s ad-level metric rows older than %s", removed, before)
    return removed


def purge_breakdowns(db: Session, *, before: date) -> int:
    removed = _purge(db, MetricsBreakdown, MetricsBreakdown.date < before)
    if removed:
        logger.info("purged %s breakdown rows older than %s", removed, before)
    return removed


def report_unfinished_figures(db: Session, *, now: datetime) -> int:
    from app.modules.ads.selectors import last_sync_outcomes, nightly_swept_accounts

    ready = now - timedelta(hours=FIGURES_NEW_ACCOUNT_HOURS)
    watched = [
        (account.id, account.external_id)
        for account in nightly_swept_accounts(db)
        if account.created_at < ready
    ]
    if not watched:
        return 0
    said = last_sync_outcomes(sweep=FIGURES_SWEEP, ad_account_ids=[str(pk) for pk, _ in watched])
    died = [name for pk, name in watched if said.get(str(pk)) == SYNC_STARTED]
    never = [name for pk, name in watched if str(pk) not in said]
    failed = [name for pk, name in watched if said.get(str(pk), "").startswith(FAILED_OUTCOMES)]
    if not died and not never and not failed:
        return 0
    logger.error(
        "the night's figures did not finish",
        extra={
            "died": len(died),
            "never_ran": len(never),
            "failed": len(failed),
            "watched": len(watched),
            "died_accounts": died[:FIGURES_REPORT_SAMPLE],
            "never_ran_accounts": never[:FIGURES_REPORT_SAMPLE],
            "failed_accounts": failed[:FIGURES_REPORT_SAMPLE],
        },
    )
    return len(died) + len(never) + len(failed)


def save_cards(db: Session, *, owner: User, keys: Iterable[str]) -> tuple[CardKey, ...]:
    chosen = chosen_keys(list(keys))
    row = db.scalars(select(MetricPreference).where(MetricPreference.owner_id == owner.id)).first()
    if row is None:
        row = MetricPreference(owner_id=owner.id)
        db.add(row)
    row.chosen = list(chosen)
    db.flush()
    return chosen
