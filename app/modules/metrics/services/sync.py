"""Reading figures from the provider: the nightly window, today, segments,
people counts, and the accounts we only watch."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from logging import Logger

from adskit import registry
from adskit.dto import MetricsDTO, SegmentMetricsDTO
from adskit.errors import (
    AuthFailed,
    PermissionDenied,
    ProviderError,
    RateLimited,
    ResultTruncated,
    TemporaryFailure,
)
from adskit.refs import ExternalRef, ProviderName
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.db import utcnow
from app.modules.ads.exceptions import (
    ConnectionUnusable,
    SyncAlreadyRunning,
    SyncFailed,
)
from app.modules.ads.services.access import token_for
from app.modules.integrations.constants import (
    USABLE_CONNECTION_STATUSES,
    ConnectionStatus,
)
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import (
    BACKFILL_DAYS,
    BREAKDOWN_BACKFILL_DAYS,
    BREAKDOWN_CHUNK_DAYS,
    BREAKDOWN_LEVEL,
    BREAKDOWN_RETENTION_DAYS,
    INSIGHT_LEVELS,
    INSIGHTS_LOCK_SECONDS,
    MIN_READ_DAYS,
    NIGHTLY_BREAKDOWNS,
    PEOPLE_LEVELS,
    PEOPLE_REFRESH_SECONDS,
    PERIOD_LENGTHS,
    RESTATE_DAYS,
    MetricLevel,
)
from app.modules.metrics.exceptions import AccountUnreadable
from app.modules.metrics.selectors.facts import (
    newest_metrics_date,
    observed_window,
    people_synced_at,
    watched_campaigns,
    watched_groups,
)
from app.modules.metrics.selectors.segments import newest_breakdown_date
from app.modules.metrics.services.store import (
    replace_people,
    store_breakdowns,
    store_metrics,
)

logger = logging.getLogger(__name__)
TRUNCATED = "truncated"
RATE_LIMITED = "rate_limited"
TEMPORARY = "temporary"
PROVIDER_ERROR = "provider_error"
PEOPLE_STEP = "people"


# -- what a failed call means ---------------------------------------------------------


def refusal_is_the_accounts(
    db: Session, ad_account: AdAccount, *, exc: PermissionDenied
) -> bool:
    """A refusal with a token Meta still calls valid lost one account, not the login."""
    from app.modules.integrations.services import mark_unusable, verify_connection

    connection = ad_account.connection
    if verify_connection(db, connection=connection):
        return True
    db.refresh(connection, attribute_names=["status"])
    if connection.status in USABLE_CONNECTION_STATUSES:
        mark_unusable(
            db, connection=connection, status=ConnectionStatus.INVALID, code=exc.code
        )
        db.commit()
    return False


def _mark_invalid(db: Session, ad_account: AdAccount, exc: AuthFailed) -> None:
    from app.modules.integrations.services import mark_unusable

    mark_unusable(
        db,
        connection=ad_account.connection,
        status=ConnectionStatus.INVALID,
        code=exc.code,
    )
    db.commit()


@contextmanager
def provider_failures(
    db: Session, ad_account: AdAccount, *, doing: str, logger: Logger
) -> Iterator[None]:
    try:
        yield
    except AuthFailed as exc:
        _mark_invalid(db, ad_account, exc)
        raise ConnectionUnusable from exc
    except PermissionDenied as exc:
        if refusal_is_the_accounts(db, ad_account, exc=exc):
            logger.warning(
                "metrics for %s at %s refused with a working token: %s",
                ad_account.external_id,
                doing,
                exc,
            )
            raise SyncFailed(cause=PROVIDER_ERROR) from exc
        raise ConnectionUnusable from exc
    except ResultTruncated as exc:
        logger.error(
            "metrics for %s at %s truncated after %s pages (%s rows)",
            ad_account.external_id,
            doing,
            exc.pages,
            exc.rows_read,
        )
        raise SyncFailed(cause=TRUNCATED) from exc
    except RateLimited as exc:
        logger.warning(
            "metrics for %s at %s hit the call budget: %s",
            ad_account.external_id,
            doing,
            exc,
        )
        raise SyncFailed(cause=RATE_LIMITED) from exc
    except TemporaryFailure as exc:
        logger.warning(
            "metrics for %s at %s: the provider is temporarily unavailable: %s",
            ad_account.external_id,
            doing,
            exc,
        )
        raise SyncFailed(cause=TEMPORARY) from exc
    except ProviderError as exc:
        logger.warning(
            "metrics for %s at %s failed: %s", ad_account.external_id, doing, exc
        )
        raise SyncFailed(cause=PROVIDER_ERROR) from exc


@contextmanager
def watched_account_failures(
    db: Session, ad_account: AdAccount, *, logger: Logger
) -> Iterator[None]:
    try:
        yield
    except AuthFailed as exc:
        _mark_invalid(db, ad_account, exc)
        raise ConnectionUnusable from exc
    except PermissionDenied as exc:
        logger.info(
            "no longer allowed to read the watched account %s: %s",
            ad_account.external_id,
            exc,
        )
        raise AccountUnreadable from exc
    except ResultTruncated as exc:
        logger.error(
            "the watched account %s answered with more than the read allows (%s pages, %s rows)",
            ad_account.external_id,
            exc.pages,
            exc.rows_read,
        )
        raise SyncFailed(cause=TRUNCATED) from exc
    except RateLimited as exc:
        logger.warning(
            "the watched account %s hit the call budget: %s",
            ad_account.external_id,
            exc,
        )
        raise SyncFailed(cause=RATE_LIMITED) from exc
    except TemporaryFailure as exc:
        logger.warning(
            "the watched account %s: the provider is temporarily unavailable: %s",
            ad_account.external_id,
            exc,
        )
        raise SyncFailed(cause=TEMPORARY) from exc
    except ProviderError as exc:
        logger.warning(
            "the watched account %s could not be read: %s", ad_account.external_id, exc
        )
        raise SyncFailed(cause=PROVIDER_ERROR) from exc


def account_ref_for(ad_account: AdAccount) -> ExternalRef:
    return ExternalRef(
        provider=ProviderName(ad_account.provider),
        level="account",
        id=ad_account.external_id,
    )


def account_today(ad_account: AdAccount) -> date:
    return utcnow().astimezone(ad_account.tzinfo()).date()


def lock_key(ad_account: AdAccount) -> str:
    return f"metrics:sync:{ad_account.provider}:{ad_account.external_id}"


@contextmanager
def _locked(ad_account: AdAccount) -> Iterator[None]:
    key = lock_key(ad_account)
    if not cache.add(key, "1", INSIGHTS_LOCK_SECONDS):
        raise SyncAlreadyRunning
    try:
        yield
    finally:
        cache.delete(key)


# -- summaries --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LevelSummary:
    level: str
    rows: int
    since: date
    until: date
    calls: int = 1


@dataclass(frozen=True, slots=True)
class BreakdownSummary:
    kind: str
    rows: int
    since: date
    until: date
    calls: int = 1


@dataclass(frozen=True, slots=True)
class InsightSummary:
    levels: tuple[LevelSummary, ...] = ()
    breakdowns: tuple[BreakdownSummary, ...] = ()
    stopped_at: str = ""
    stopped_by: str = ""
    unread: tuple[str, ...] = ()

    @property
    def rows(self) -> int:
        return sum(level.rows for level in self.levels)

    @property
    def segment_rows(self) -> int:
        return sum(cut.rows for cut in self.breakdowns)

    @property
    def calls(self) -> int:
        return sum(level.calls for level in self.levels) + sum(
            cut.calls for cut in self.breakdowns
        )

    @property
    def complete(self) -> bool:
        return not self.stopped_at


# -- reading one level ----------------------------------------------------------------


def read_level(
    db: Session, ad_account: AdAccount, *, since: date, until: date, level: str
) -> list[MetricsDTO]:
    bundle = registry.get(ad_account.provider)
    with provider_failures(db, ad_account, doing=str(level), logger=logger):
        return bundle.metrics.fetch_daily(
            account=account_ref_for(ad_account),
            since=since,
            until=until,
            level=str(level),
            token=token_for(ad_account=ad_account),
        )


def window(
    db: Session, *, ad_account: AdAccount, today: date, level: str
) -> tuple[date, date]:
    newest = newest_metrics_date(db, ad_account=ad_account, level=level)
    if newest is None:
        return today - timedelta(days=BACKFILL_DAYS - 1), today
    return min(newest, today - timedelta(days=RESTATE_DAYS - 1)), today


def _fill(
    db: Session, ad_account: AdAccount, *, since: date, until: date, level: str
) -> tuple[int, int]:
    pieces = [(since, until)]
    rows = calls = 0
    while pieces:
        start, end = pieces.pop(0)
        calls += 1
        try:
            found = read_level(db, ad_account, since=start, until=end, level=level)
        except SyncFailed as exc:
            span = (end - start).days + 1
            if exc.cause != TEMPORARY or span <= MIN_READ_DAYS:
                raise
            middle = start + timedelta(days=span // 2 - 1)
            pieces[:0] = [(start, middle), (middle + timedelta(days=1), end)]
            logger.info(
                "insights for %s at %s refused for %s days, halving",
                ad_account.external_id,
                level,
                span,
            )
            continue
        store_metrics(db, ad_account=ad_account, rows=found, now=utcnow(), level=level)
        rows += len(found)
    return rows, calls


# -- the nightly read ------------------------------------------------------------------


def sync_insights(db: Session, *, ad_account: AdAccount) -> InsightSummary:
    with _locked(ad_account):
        today = account_today(ad_account)
        done: list[LevelSummary] = []
        for level in INSIGHT_LEVELS:
            since, until = window(db, ad_account=ad_account, today=today, level=level)
            try:
                rows, calls = _fill(
                    db, ad_account, since=since, until=until, level=level
                )
            except SyncFailed as exc:
                if not done:
                    raise
                logger.info(
                    "insights for %s stopped at %s (%s) after %s",
                    ad_account.external_id,
                    level,
                    exc.cause,
                    [entry.level for entry in done],
                )
                return InsightSummary(
                    levels=tuple(done), stopped_at=str(level), stopped_by=exc.cause
                )
            done.append(
                LevelSummary(
                    level=str(level), rows=rows, since=since, until=until, calls=calls
                )
            )
        try:
            sync_people(db, ad_account=ad_account, today=today)
        except SyncFailed as exc:
            logger.info(
                "people counts for %s stopped (%s)", ad_account.external_id, exc.cause
            )
            return InsightSummary(
                levels=tuple(done), stopped_at=PEOPLE_STEP, stopped_by=exc.cause
            )
        cuts: list[BreakdownSummary] = []
        stopped = why = ""
        for kind in NIGHTLY_BREAKDOWNS:
            try:
                cuts.append(
                    sync_breakdown(db, ad_account=ad_account, today=today, kind=kind)
                )
            except SyncFailed as exc:
                logger.info(
                    "breakdowns for %s stopped at %s (%s)",
                    ad_account.external_id,
                    kind,
                    exc.cause,
                )
                stopped, why = str(kind), exc.cause
                break
        summary = InsightSummary(
            levels=tuple(done),
            breakdowns=tuple(cuts),
            stopped_at=stopped,
            stopped_by=why,
        )
        logger.info(
            "insights for %s: %s rows, %s segment rows, %s calls%s",
            ad_account.external_id,
            summary.rows,
            summary.segment_rows,
            summary.calls,
            "" if summary.complete else f", stopped at {stopped} ({why})",
        )
        return summary


# -- today -------------------------------------------------------------------------------


def sync_today(
    db: Session, *, ad_account: AdAccount, people_after: timedelta | None = None
) -> InsightSummary:
    with _locked(ad_account):
        older_than = people_after or timedelta(seconds=PEOPLE_REFRESH_SECONDS)
        today = account_today(ad_account)
        done: list[LevelSummary] = []
        unread: list[str] = []
        for level in INSIGHT_LEVELS:
            if newest_metrics_date(db, ad_account=ad_account, level=level) is None:
                unread.append(str(level))
                continue
            try:
                rows = read_level(db, ad_account, since=today, until=today, level=level)
            except SyncFailed as exc:
                logger.info(
                    "today's insights for %s stopped at %s (%s)",
                    ad_account.external_id,
                    level,
                    exc.cause,
                )
                return InsightSummary(
                    levels=tuple(done),
                    stopped_at=str(level),
                    stopped_by=exc.cause,
                    unread=tuple(unread),
                )
            store_metrics(
                db, ad_account=ad_account, rows=rows, now=utcnow(), level=level
            )
            done.append(
                LevelSummary(level=str(level), rows=len(rows), since=today, until=today)
            )
        if done:
            synced = people_synced_at(db, ad_account=ad_account, until=today)
            if not synced or utcnow() - synced >= older_than:
                try:
                    sync_people(db, ad_account=ad_account, today=today)
                except SyncFailed as exc:
                    logger.info(
                        "people counts for %s stopped (%s)",
                        ad_account.external_id,
                        exc.cause,
                    )
        return InsightSummary(levels=tuple(done), unread=tuple(unread))


# -- the whole history again --------------------------------------------------------------


def refill_history(db: Session, *, ad_account: AdAccount) -> int:
    def read_store(since: date, until: date, level: str) -> int:
        try:
            rows = read_level(db, ad_account, since=since, until=until, level=level)
        except SyncFailed as exc:
            if since == until or exc.cause not in (TEMPORARY, TRUNCATED):
                raise
            middle = since + timedelta(days=(until - since).days // 2)
            return read_store(since, middle, level) + read_store(
                middle + timedelta(days=1), until, level
            )
        return store_metrics(
            db, ad_account=ad_account, rows=rows, now=utcnow(), level=level
        )

    with _locked(ad_account):
        today = account_today(ad_account)
        written = 0
        for level in INSIGHT_LEVELS:
            for since, until in chunks(
                since=today - timedelta(days=BACKFILL_DAYS - 1), until=today
            ):
                written += read_store(since, until, str(level))
        return written


# -- segments ------------------------------------------------------------------------------


def retention_floor(*, today: date) -> date:
    return today - timedelta(days=BREAKDOWN_RETENTION_DAYS - 1)


def chunks(*, since: date, until: date) -> list[tuple[date, date]]:
    pieces: list[tuple[date, date]] = []
    start = since
    while start <= until:
        end = min(start + timedelta(days=BREAKDOWN_CHUNK_DAYS - 1), until)
        pieces.append((start, end))
        start = end + timedelta(days=1)
    return pieces


def breakdown_window(
    db: Session, *, ad_account: AdAccount, today: date, kind: str
) -> tuple[date, date]:
    newest = newest_breakdown_date(
        db, owner=ad_account.owner, kind=kind, account=ad_account
    )
    start = (
        today - timedelta(days=BREAKDOWN_BACKFILL_DAYS - 1)
        if newest is None
        else min(newest, today - timedelta(days=RESTATE_DAYS - 1))
    )
    return max(start, retention_floor(today=today)), today


def sync_breakdown(
    db: Session, *, ad_account: AdAccount, today: date, kind: str
) -> BreakdownSummary:
    since, until = breakdown_window(db, ad_account=ad_account, today=today, kind=kind)
    stored = calls = 0
    bundle = registry.get(ad_account.provider)
    for start, end in chunks(since=since, until=until):
        with provider_failures(
            db, ad_account, doing=f"breakdown {kind}", logger=logger
        ):
            rows: list[SegmentMetricsDTO] = bundle.metrics.fetch_breakdown(
                account=account_ref_for(ad_account),
                since=start,
                until=end,
                level=str(BREAKDOWN_LEVEL),
                kind=kind,
                token=token_for(ad_account=ad_account),
            )
        store_breakdowns(
            db,
            ad_account=ad_account,
            rows=rows,
            now=utcnow(),
            level=str(BREAKDOWN_LEVEL),
        )
        stored += len(rows)
        calls += 1
    return BreakdownSummary(
        kind=str(kind), rows=stored, since=since, until=until, calls=calls
    )


# -- people ----------------------------------------------------------------------------------


def people_ranges(today: date) -> list[tuple[date, date]]:
    ranges: list[tuple[date, date]] = []
    for days in sorted(set(PERIOD_LENGTHS.values())):
        since = today - timedelta(days=days - 1)
        ranges.append((since, today))
        ranges.append((since - timedelta(days=days), since - timedelta(days=1)))
    return ranges


def sync_people(db: Session, *, ad_account: AdAccount, today: date) -> int:
    ranges = people_ranges(today)
    bundle = registry.get(ad_account.provider)
    written = 0
    for level in PEOPLE_LEVELS:
        with provider_failures(db, ad_account, doing=f"people:{level}", logger=logger):
            rows = bundle.metrics.fetch_people(
                account=account_ref_for(ad_account),
                ranges=ranges,
                level=str(level),
                token=token_for(ad_account=ad_account),
            )
        written += replace_people(
            db, ad_account=ad_account, level=str(level), rows=rows, now=utcnow()
        )
    return written


# -- accounts we only watch -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObservedSummary:
    offered: int = 0
    rows: int = 0
    since: date | None = None
    until: date | None = None
    still_delivering: bool = False


def sync_observed(
    db: Session, *, ad_account: AdAccount, now: datetime
) -> ObservedSummary:
    from app.modules.integrations.services import note_lead_sighting

    with _locked(ad_account):
        groups = watched_groups(db, ad_account=ad_account)
        if not groups:
            return ObservedSummary()
        since, until = observed_window(
            db, ad_account=ad_account, today=account_today(ad_account)
        )
        offered = kept = 0
        campaigns = watched_campaigns(db, ad_account=ad_account)
        adset_rows: list[MetricsDTO] = []
        bundle = registry.get(ad_account.provider)
        for level in INSIGHT_LEVELS:
            with watched_account_failures(db, ad_account, logger=logger):
                rows = bundle.metrics.fetch_daily(
                    account=account_ref_for(ad_account),
                    since=since,
                    until=until,
                    level=str(level),
                    token=token_for(ad_account=ad_account),
                )
            if level == MetricLevel.CAMPAIGN:
                mine = [row for row in rows if row.campaign_external_id in campaigns]
            else:
                mine = [row for row in rows if row.adset_external_id in groups]
            store_metrics(
                db, ad_account=ad_account, rows=mine, now=utcnow(), level=level
            )
            offered += len(rows)
            kept += len(mine)
            if level == MetricLevel.ADSET:
                adset_rows = mine
                campaigns |= {row.campaign_external_id for row in mine} - {""}
        delivering = _still_delivering(
            db, ad_account=ad_account, adsets=adset_rows, now=now
        )
        if delivering:
            note_lead_sighting(db, account=ad_account, at=now)
            db.commit()
        logger.info(
            "observed %s: %s of %s rows kept, %s to %s%s",
            ad_account.external_id,
            kept,
            offered,
            since,
            until,
            "" if delivering else ", no longer delivering",
        )
        return ObservedSummary(
            offered=offered,
            rows=kept,
            since=since,
            until=until,
            still_delivering=delivering,
        )


def _still_delivering(
    db: Session, *, ad_account: AdAccount, adsets: list[MetricsDTO], now: datetime
) -> bool:
    from app.modules.integrations.selectors import OBSERVE_DAYS
    from app.modules.leads.models import Lead

    if not adsets:
        return False
    return (
        db.scalar(
            select(Lead.id)
            .where(
                Lead.owner_id == ad_account.owner_id,
                Lead.is_test.is_(False),
                Lead.provider == ad_account.provider,
                Lead.adset_external_id.in_({row.adset_external_id for row in adsets}),
                Lead.submitted_at >= now - timedelta(days=OBSERVE_DAYS),
            )
            .limit(1)
        )
        is not None
    )


def sync_all_observed(db: Session, *, now: datetime, hour: int | None = None) -> int:
    from app.modules.integrations.selectors import observed_accounts, owners_at_hour
    from app.modules.metrics.tasks import sync_observed_task

    rows = [
        (account.id, account.owner_id) for account in observed_accounts(db, now=now)
    ]
    if hour is not None:
        due = owners_at_hour(
            db, owner_ids={owner for _, owner in rows}, now=now, hour=hour
        )
        rows = [row for row in rows if str(row[1]) in due]
    for account_id, _owner in rows:
        sync_observed_task.delay(str(account_id))
    return len(rows)
